#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orchestrierung: .ats -> .story (convert_ats)."""
from __future__ import annotations

import dataclasses
import os
import re
import sys
import zipfile
from collections.abc import Callable
from typing import Literal

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

from .ats_reader import course_background, detect_canvas, slide_content, walk_course
from .geometry import Geometry
from .guid import newg, relid_from_guid
from .media import MediaPool
from .ocr import config as ocr_config
from .ocr import ocr_lang
from .story_writer import (
    Builder,
    Template,
    add_media_pool,
    build_summary,
    clean_backgrounds,
    patch_story_xml,
    set_story_size,
    strip_quiz,
    write_story_package,
)
from . import quiz_bank as _bank
from .quiz_export import collect_questions, write_text, write_xlsx
from .types import ConvertStats

def _default_skeleton() -> str:
    """Pfad zum eingebauten Storyline-Grundgerüst (Dev-Lauf UND PyInstaller-Bundle).

    Ersetzt die früher nötige externe Vorlage: das minimale, gestrippte Gerüst
    (Master/Layouts/Theme/Player + Form-Schablonen) liegt als Paket-Asset bei.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(here, 'assets', 'skeleton.story')
    if os.path.isfile(cand):
        return cand
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = os.path.join(meipass, 'ats2story', 'assets', 'skeleton.story')
        if os.path.isfile(bundled):
            return bundled
    return cand


#: Eingebautes Storyline-Grundgerüst (keine externe Vorlage mehr nötig).
DEF_TPL = _default_skeleton()
#: Default-Quell-Kurs (nur Rückfall, wenn weder Positional noch ``--ats`` kommt).
#: Bewusst NEUTRAL: hier stand der Dateiname eines Kundenkurses, der damit im
#: ausgelieferten Paket und in jeder Hilfeausgabe auftauchte.
DEF_ATS = 'kurs.ats'


def _slide_partname(n: int) -> str:
    """Hex-Folien-Name wie Storyline: slide.xml, slide2, … slide9, slidea …"""
    if n == 1:
        return 'slide.xml'
    return f'slide{format(n, "x")}.xml'


def convert_ats(ats: str, out: str, tpl: str = DEF_TPL, chapters: str | None = None,
                max_slides: int = 0, no_audio: bool = False, ocr_text: bool = False,
                no_exams: bool = True, single_scene: bool = False, scene_name: str = 'Kurs',
                keep_medialst: bool = False, keep_quiz: bool = False, clean_bg: bool = False,
                geometry: Literal['fit', 'fill', 'native'] = 'fit',
                course_bg: bool = True, quiz_export: bool = False,
                quiz_slides: bool = False, quiz_bank: bool = True,
                quiz_font_pt: float | None = None,
                progress: Callable[[float, str], None] | None = None) -> dict:
    """Konvertiert eine .ats-Datei -> .story.

    ``geometry``: 'fit' (letterbox, Standard, kein Inhaltsverlust), 'fill'
    (crop-to-fill, Vollbild — Rand-Überstände werden abgeschnitten) oder
    'native' (Story-Size = imc-Canvas, Koordinaten 1:1 übernommen). Der
    imc-Canvas wird pro Kurs erkannt (Geräteprofile unterscheiden sich).
    ``course_bg``: Kurs-Hintergrundbild als unterste Ebene je Folie übernehmen.
    ``no_exams``: die Platzhalterfolien der imc-Prüfungen weglassen —
    standardmäßig AN. Sie waren ein Notbehelf aus der Zeit, als die Fragen
    nirgends hinkonnten; seit die Fragen als Fragenbank in der .story landen,
    steht dort nur noch ein roter Merkzettel im Weg.
    ``quiz_slides``: Quizfragen zusätzlich als Folien in die .story legen.
    Standardmäßig AUS — die Fragen gehen über ``quiz_export`` als Importdatei
    heraus, woraus Storyline echte Quizfolien baut; als Folien wären sie nur
    eine statische Abbildung und verdrängen in fragenlastigen Kursen alles
    andere (ein reiner Prüfungskurs kann 1 Inhaltsfolie und über 200 Fragen haben).
    ``quiz_export``: Quizfragen zusätzlich als Articulate-Importdatei ablegen
    (``…_Fragen.xlsx`` und ``.txt`` neben der .story) — daraus baut Storyline
    beim Import ECHTE Quizfolien statt unserer Text-Ersatzdarstellung.
    ``progress``: optionaler Callback ``progress(frac, msg)`` für GUIs.
    Rückgabe: dict (asdict von ConvertStats) mit denselben Keys wie bisher.
    """
    def emit(frac: float, msg: str) -> None:
        if progress is not None:
            progress(frac, msg)
        else:
            print(msg)

    emit(0.02, f'Lade Vorlage {os.path.basename(tpl)} ...')
    tplo = Template(tpl)
    if not (tplo.pic_stencil and tplo.tb_stencil and tplo.snd_stencil):
        raise ValueError('Stencil fehlt in Vorlage — pic/textBox/sound-Shape fehlen in slide.xml!')
    if clean_bg:
        res = clean_backgrounds(tplo)
        emit(0.04, f'Hintergrund gesäubert ({res.images} Hintergrundbild(er), '
             f'{res.fills} Farbfläche(n) → weiß)')

    emit(0.05, f'Lese Kurs {os.path.basename(ats)} ...')
    with zipfile.ZipFile(ats) as atsz:
        scenes = walk_course(atsz)
        background = course_background(atsz) if course_bg else {}
    scenes = _filter_scenes(scenes, chapters, no_exams, single_scene, scene_name)
    # Fragen EINSAMMELN, bevor sie ggf. aus den Folien fallen — sonst wäre die
    # Importdatei leer (genau das war hier schon einmal kaputt).
    # Die Fragen werden gebraucht, sobald EINE der beiden Ausgaben sie will.
    # Hing das nur am Excel-Export, kam bei abgeschaltetem Excel auch keine
    # Fragenbank heraus — ein reiner Prüfungskurs lieferte eine leere .story.
    questions = (collect_questions(scenes, slide_content)
                 if (quiz_export or quiz_bank) else [])
    quiz_total = sum(1 for sc in scenes for s in sc['slides'] if s.get('quiz'))
    if not quiz_slides and quiz_total:
        for sc in scenes:
            sc['slides'] = [s for s in sc['slides'] if not s.get('quiz')]
        scenes = [sc for sc in scenes if sc['slides']]
        emit(0.054, f'  {quiz_total} Fragen bleiben aus den Folien '
                    f'(gehen als Importdatei heraus)')
    total = sum(len(sc['slides']) for sc in scenes)
    if max_slides:
        total = min(total, max_slides)
    emit(0.055, f'  {len(scenes)} Szenen, {total} Folien')

    # Canvas des Kurses ERKENNEN (Geräteprofile unterscheiden sich: 1024x748
    # und 950x630 sind belegt). Fest verdrahtete Maße verschieben und skalieren
    # sonst jede Folie eines abweichenden Kurses.
    cw, ch = detect_canvas(scenes)
    geom = Geometry(geometry, cw, ch)
    emit(0.058, f'  imc-Canvas erkannt: {cw}x{ch} → Storyline {geom.story_w}x{geom.story_h} '
         f'({geom.mode}, Faktor {geom.scale:.3f})')
    if geometry == 'native':
        set_story_size(tplo, geom.story_w, geom.story_h)
        emit(0.06, f'Story-Size auf {geom.story_w}x{geom.story_h} (imc-Canvas) gestellt')
    if background.get('image'):
        emit(0.06, f'  Kurs-Hintergrund übernommen: {background.get("name")}')

    pool = MediaPool()
    builder = Builder(tplo, pool, with_audio=not no_audio, ocr_text=ocr_text,
                      geometry=geom, background=background,
                      quiz_slides=quiz_slides, quiz_export=quiz_export,
                      quiz_bank=quiz_bank)
    if ocr_text:
        lg = ocr_lang()
        emit(0.06, f'OCR aktiv: Engine=tesseract, Sprache={lg or "KEINE!"}'
             + ('' if lg == 'deu' else '  (WARN: deu fehlt -> Umlaute evtl. ungenau; ATS_TESSDATA setzen)'))

    built = _build_slides(builder, scenes, pool, total, max_slides, emit)
    scenes_built, new_slide_parts, new_slide_rels, slides_flat, produced = built

    # --- Fragenbank: das imc-Depot als echte Storyline-Fragefolien ---------
    bank_slides: list = []
    bank_skipped: dict = {}
    if quiz_bank and questions:
        if not _bank.available():
            # Ohne Vorlage keine Bank. Ohne Rückfall wären die Fragen dann
            # NIRGENDS — der Excel-Export ist standardmäßig aus. Genau so ist
            # eine .story ohne einzige Frage entstanden.
            emit(0.86, '  !! Fragenbank-Vorlage fehlt — Fragen gehen stattdessen '
                       'als Importdatei heraus')
            quiz_export = True
        else:
            # Eine Angabe genügt: die Antworten wachsen im selben
            # Verhältnis mit wie in der Vorlage (18,5 zu 12 pt).
            t_pt = float(quiz_font_pt or _bank.DEFAULT_TITLE_PT)
            c_pt = round(_bank.DEFAULT_CHOICE_PT * t_pt / _bank.DEFAULT_TITLE_PT, 1)
            bank_slides, bank_skipped = _bank.build_bank(questions, t_pt, c_pt)
            idx = len(slides_flat)
            for bs in bank_slides:
                idx += 1
                partname = _slide_partname(idx)
                new_slide_parts['story/slides/' + partname] = bs.xml.encode('utf-8')
                new_slide_rels['story/slides/_rels/' + partname + '.rels'] = bs.rels.encode('utf-8')
                # Über slides_flat laufen Rels UND Content-Types automatisch mit.
                slides_flat.append((relid_from_guid(bs.guid), partname))
                pool.files.update(bs.media)
            if not bank_slides:
                emit(0.87, '  !! keine einzige Frage baubar — sie gehen als '
                           'Importdatei heraus')
                quiz_export = True
            elif bank_skipped:
                # Die nicht baubaren Fragen dürfen nicht unter den Tisch
                # fallen; die Importdatei enthält sie alle.
                quiz_export = True
            emit(0.87, f'  {len(bank_slides)} Fragen als Fragenbank angelegt'
                 + (f'; {sum(bank_skipped.values())} nicht baubar '
                    f'({", ".join(f"{k}: {v}" for k, v in sorted(bank_skipped.items()))})'
                    if bank_skipped else ''))

    # Ein reiner Prüfungskurs besteht nur aus Fragen; nach dem Aussortieren
    # der Frage- und Platzhalterfolien blieb NICHTS übrig — eine .story ohne
    # eine einzige Szene, deren Startverweis zudem ins Leere zeigte. Eine
    # Hinweisfolie hält die Datei zusammen und sagt, wo die Fragen liegen.
    if not scenes_built and (bank_slides or questions):
        info = dict(exam=True, info=True, name='Fragen dieses Kurses',
                    q_total=len(bank_slides) or len(questions),
                    q_new=len(bank_slides) or len(questions))
        partname = _slide_partname(len(slides_flat) + 1)
        sld_xml, rels_xml, sld_guid, _d, _u = builder.build_slide(info, partname, 1)
        new_slide_parts['story/slides/' + partname] = sld_xml.encode('utf-8')
        new_slide_rels['story/slides/_rels/' + partname + '.rels'] = rels_xml.encode('utf-8')
        rid = relid_from_guid(sld_guid)
        vg = re.search(r'<sld\b[^>]*\sverG="([0-9a-fA-F-]{36})"', sld_xml)
        slides_flat.insert(0, (rid, partname))
        scenes_built.append(dict(name='Kurs', scene_guid=newg(), sldids=[rid],
                                 slides=[dict(relid=rid, sld_guid=sld_guid, partname=partname,
                                              name=info['name'],
                                              verg=vg.group(1) if vg else newg())]))
        produced = 1
        emit(0.87, '  Kurs ohne Inhaltsfolien — Hinweisfolie auf die Fragen angelegt')

    ocr_conf = (builder.ocr_conf_sum / builder.ocr_replaced) if builder.ocr_replaced else 0
    emit(0.86, f'Folien erzeugt: {produced}; Mediendateien: {len(pool.files)}'
         + (f'; OCR: {builder.ocr_replaced} Text-Bilder editierbar (Ø {ocr_conf:.0f}%)' if ocr_text else ''))

    emit(0.88, 'Baue story.xml ...')
    story, rels, ct, summary_xml = _build_xml(tplo, scenes_built, pool, slides_flat,
                                              keep_medialst, keep_quiz, bank_slides)

    emit(0.92, f'Schreibe {os.path.basename(out)} ...')
    bad = write_story_package(out, tplo, story, rels, ct, summary_xml,
                              new_slide_parts, new_slide_rels, pool, keep_medialst)
    size = os.path.getsize(out)

    quiz_files: list[str] = []
    if quiz_export and questions:
        quiz_files = _write_quiz_files(out, questions, emit)

    stats = _make_stats(out, produced, scenes_built, pool, size, builder, ocr_conf, bad)
    stats = dataclasses.replace(stats, bank_slides=len(bank_slides),
                                bank_skipped=dict(bank_skipped))
    stats = dataclasses.replace(stats, quiz_files=quiz_files)
    emit(1.0, _final_msg(out, size, produced, pool, bad, stats))
    return dataclasses.asdict(stats)


def _filter_scenes(scenes, chapters, no_exams, single_scene, scene_name):
    """Kapitel-/Exam-/Single-Scene-Filter anwenden."""
    if chapters:
        subs = [s.strip().lower() for s in chapters.split(',') if s.strip()]
        scenes = [sc for sc in scenes if any(x in sc['name'].lower() for x in subs)]
    if no_exams:
        for sc in scenes:
            sc['slides'] = [s for s in sc['slides'] if not s.get('exam')]
        scenes = [sc for sc in scenes if sc['slides']]
    if single_scene:
        merged = [s for sc in scenes for s in sc['slides']]
        scenes = [dict(name=scene_name, slides=merged)] if merged else []
    return scenes


def _build_slides(builder, scenes, pool, total, max_slides, emit):
    """Alle Folien bauen + XML-validieren. -> (scenes_built, parts, rels, flat, produced)."""
    new_slide_parts: dict[str, bytes] = {}
    new_slide_rels: dict[str, bytes] = {}
    scenes_built: list[dict] = []
    slides_flat: list[tuple] = []
    idx = 0
    produced = 0
    for sc in scenes:
        sb = dict(name=sc['name'], scene_guid=newg(), sldids=[], slides=[])
        for s in sc['slides']:
            idx += 1
            partname = _slide_partname(idx)
            sld_xml, rels_xml, sld_guid, _dur, _used = builder.build_slide(s, partname, idx)
            try:
                ET.fromstring(sld_xml.encode('utf-8'))
            except ET.ParseError as ex:
                emit(0.05, f'  !! Folie {idx} ({s.get("name")}) XML-Fehler: {ex} -> übersprungen')
                idx -= 1
                continue
            rid = relid_from_guid(sld_guid)
            vg = re.search(r'<sld\b[^>]*\sverG="([0-9a-fA-F-]{36})"', sld_xml)
            verg = vg.group(1) if vg else newg()
            new_slide_parts['story/slides/' + partname] = sld_xml.encode('utf-8')
            new_slide_rels['story/slides/_rels/' + partname + '.rels'] = rels_xml.encode('utf-8')
            sb['sldids'].append(rid)
            sb['slides'].append(dict(relid=rid, sld_guid=sld_guid, partname=partname,
                                     name=s.get('name', 'Folie'), verg=verg))
            slides_flat.append((rid, partname))
            produced += 1
            frac = 0.06 + 0.79 * (produced / total if total else 1)
            emit(min(0.85, frac), f'  ... {produced}/{total} Folien, {len(pool.files)} Mediendateien')
            if max_slides and produced >= max_slides:
                break
        if sb['slides']:
            scenes_built.append(sb)
        if max_slides and produced >= max_slides:
            break
    return scenes_built, new_slide_parts, new_slide_rels, slides_flat, produced


def _build_xml(tplo, scenes_built, pool, slides_flat, keep_medialst, keep_quiz,
               bank_slides=()):
    """story.xml / rels / Content-Types / summary bauen + validieren."""
    story = tplo.story
    story = patch_story_xml(story, scenes_built)
    if keep_medialst:
        OPEN = '<mediaLst><mediaLst>'
        a = story.find(OPEN)
        if a == -1:
            raise ValueError('keep_medialst: <mediaLst><mediaLst> nicht in story.xml gefunden')
        story = story[:a + len(OPEN)] + ''.join(pool.entries_xml) + story[a + len(OPEN):]
    else:
        story = add_media_pool(story, pool, tplo.keep_md5)
    if not keep_quiz:
        story = strip_quiz(story, _bank.bank_scene_xml(list(bank_slides)) if bank_slides else '')
    ET.fromstring(story.encode('utf-8'))

    rels = tplo.story_rels
    rels = re.sub(r'<Relationship Type="slide"[^>]*/>', '', rels)
    slide_rel_xml = ''.join(
        f'<Relationship Type="slide" Target="/story/slides/{pn}" Id="{rid}" />'
        for rid, pn in slides_flat)
    rels = rels.replace('</Relationships>', slide_rel_xml + '</Relationships>')
    ET.fromstring(rels.encode('utf-8'))

    ct = tplo.ctypes
    ct = re.sub(r'<Override PartName="/story/slides/slide[^"]*\.xml" ContentType="application/slide\+xml" />', '', ct)
    ov = ''.join(
        f'<Override PartName="/story/slides/{pn}" ContentType="application/slide+xml" />'
        for _, pn in slides_flat)
    ct = ct.replace('</Types>', ov + '</Types>')
    ET.fromstring(ct.encode('utf-8'))

    summary_xml = build_summary(scenes_built)
    ET.fromstring(summary_xml.encode('utf-8'))
    return story, rels, ct, summary_xml


def _make_stats(out, produced, scenes_built, pool, size, builder, ocr_conf, bad) -> ConvertStats:
    """Statistik-Objekt zusammenbauen (inkl. Pro-Folie-Skip-Detail)."""
    per_slide: dict[int, dict] = {}
    for sidx, sname, _img in builder.skipped_img_log:
        d = per_slide.setdefault(sidx, {'name': sname, 'imgs': 0, 'audio': False})
        d['imgs'] += 1
    audio_reasons: list[str] = []
    for sidx, sname, why in builder.skipped_audio_log:
        d = per_slide.setdefault(sidx, {'name': sname, 'imgs': 0, 'audio': False})
        d['audio'] = True
        if why and why not in audio_reasons:
            audio_reasons.append(why)
    skipped_detail: list[str] = []
    for sidx in sorted(per_slide):
        d = per_slide[sidx]
        what = []
        if d['imgs']:
            what.append(f"{d['imgs']} Bild(er)")
        if d['audio']:
            what.append('Audio')
        skipped_detail.append(f'Folie {sidx} „{d["name"]}": {", ".join(what)} nicht übernommen')
    # Der Grund gehört an den Anfang: die Folienliste allein sagt nur DASS
    # etwas fehlt, nicht warum — und wie es sich beheben lässt.
    skipped_detail = [f'Grund: {r}' for r in audio_reasons] + skipped_detail

    return ConvertStats(
        out=out, slides=produced, scenes=len(scenes_built), media=len(pool.files),
        size=size, ocr_replaced=builder.ocr_replaced, ocr_conf=round(ocr_conf), bad=bad,
        skipped_imgs=builder.skipped_img, skipped_slides=builder.skipped_slides,
        skipped_audio=builder.skipped_audio, ocr_errors=ocr_config._ocr_errors,
        skipped_detail=skipped_detail,
        fonts=builder.fonts.most_common())


def _final_msg(out, size, produced, pool, bad, stats: ConvertStats) -> str:
    """Abschluss-Logzeile (mit Skip-Zusammenfassung)."""
    skip_parts = []
    if stats.skipped_imgs:
        skip_parts.append(f'{stats.skipped_imgs} Bild(er)')
    if stats.skipped_slides:
        skip_parts.append(f'{stats.skipped_slides} Folie(n)')
    if stats.skipped_audio:
        skip_parts.append(f'{stats.skipped_audio} Audio')
    if stats.ocr_errors:
        skip_parts.append(f'{stats.ocr_errors} OCR-Fehler')
    skip_msg = ('; übersprungen: ' + ', '.join(skip_parts)) if skip_parts else ''
    # Schriften nennen: imc liefert Web-Fonts mit dem Kurs aus, Storyline kann
    # das nicht. Fehlt eine Schrift auf dem Storyline-Rechner, ersetzt Storyline
    # sie durch eine beliebige andere — mit anderen Zeichenbreiten verschiebt
    # sich der Umbruch. Der imc-Publisher protokolliert dieselbe Information
    # ("Copying web font ..."); hier kommt sie aus dem Kurs selbst.
    font_msg = ''
    if stats.fonts:
        named = ', '.join(f'{n} ({c}x)' for n, c in stats.fonts[:4])
        rest = len(stats.fonts) - 4
        font_msg = ('\nSchriften im Kurs: ' + named + (f' u.a. ({rest} weitere)' if rest > 0 else '')
                    + '\n  Diese Schriften sollten auf dem Storyline-Rechner installiert sein — '
                      'sonst ersetzt Storyline sie und der Zeilenumbruch verschiebt sich.')
    return (f'FERTIG: {os.path.basename(out)}  ({size/1e6:.1f} MB, {produced} Folien, '
            f'{len(pool.files)} Medien, testzip={bad}{skip_msg}){font_msg}')


def _write_quiz_files(out: str, questions: list[dict], emit) -> list[str]:
    """Quizfragen als Articulate-Importdateien neben die .story legen.

    Storyline baut daraus beim Import echte, auswertbare Quizfolien. Die Fragen
    stammen aus dem ``<vault>``-Depot des Kurses, nicht aus Folien — sie werden
    deshalb eingesammelt, BEVOR die Folienliste gefiltert wird.
    """
    base = out[:-6] if out.lower().endswith('.story') else out
    files: list[str] = []
    for suffix, writer in (('_Fragen.xlsx', write_xlsx), ('_Fragen.txt', write_text)):
        path = base + suffix
        try:
            writer(questions, path)
            files.append(path)
        except Exception as exc:        # pragma: no cover - defensiv
            emit(0.95, f'  {os.path.basename(path)} nicht geschrieben: {exc}')
    kinds: dict[str, int] = {}
    for q in questions:
        kinds[q['type']] = kinds.get(q['type'], 0) + 1
    emit(0.96, f'  {len(questions)} Quizfragen exportiert '
               f'({", ".join(f"{k}: {v}" for k, v in sorted(kinds.items()))}) — '
               f'in Storyline über Datei > Import > Fragen aus Datei einlesen')
    return files
