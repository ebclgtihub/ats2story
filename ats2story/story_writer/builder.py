#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baut einzelne Storyline-Folien aus .ats-Folienquellen."""
from __future__ import annotations

import collections
import re
from typing import TYPE_CHECKING, Literal

from ..ats_reader import slide_content, slide_duration_ms
from ..geometry import Geometry
from ..media import apply_opacity
from ..ocr import ocr_textblocks
from ..ocr.imagemask import NONTEXT_KEEP_RATIO, erase_text_regions
from ..richtext import parse_richtext
from . import shapes

if TYPE_CHECKING:
    from ..media import MediaPool
    from .template import Template

MIN_DUR = 5000   # ms, Mindest-Folienlänge

#: Schriftgröße (imc-px) für Antwortoptionen ohne eigene Angabe
#: (``fontSize="-1"``) — im imc-Rendering einer Frageseite nachgemessen.
_CHOICE_DEFAULT_PX = 25


class Builder:
    """Baut Folien-XML + rels aus .ats-Folien gegen eine Vorlage.

    ``geometry`` ('fit'|'fill'|'native') steuert die Bild-/Text-Platzierung:
    'fit' = letterbox (Standard, kein Inhaltsverlust), 'fill' = crop-to-fill
    (Vollbild, Rand-Überstände werden abgeschnitten), 'native' = Identität
    (Story-Size wird auf den imc-Canvas 1024x748 gestellt, siehe
    ``set_story_size``).
    """

    def __init__(self, tpl: 'Template', pool: 'MediaPool', with_audio: bool = True,
                 ocr_text: bool = False,
                 geometry: Literal['fit', 'fill', 'native'] | Geometry = 'fit',
                 background: dict | None = None, quiz_slides: bool = False,
                 quiz_export: bool = True, quiz_bank: bool = False) -> None:
        #: Wohin die Fragen gehen — der Platzhaltertext der Prüfungsfolien muss
        #: das sagen, sonst schickt er den Leser an die falsche Stelle.
        self.quiz_slides = quiz_slides
        self.quiz_export = quiz_export
        self.quiz_bank = quiz_bank
        self.tpl = tpl
        self.pool = pool
        self.with_audio = with_audio
        self.ocr_text = ocr_text
        # ``geometry`` darf ein Modus-String (Alt-Aufrufer, Default-Canvas) oder
        # eine kalibrierte Geometry-Instanz (erkannter Kurs-Canvas) sein. Mit
        # Default-Canvas ist Geometry(mode) rechnerisch identisch zu
        # fit_rect/fill_rect/native_rect.
        self.geom = geometry if isinstance(geometry, Geometry) else Geometry(geometry)
        self.geometry = self.geom.mode
        self.rect_transform = self.geom
        self.background = background or {}
        self.bg_added = 0
        self.skipped_img = 0
        self.skipped_img_log: list[tuple] = []
        self.skipped_audio = 0
        #: (Folienindex, Folienname, Grund) — der Grund wandert in den Bericht
        self.skipped_audio_log: list[tuple] = []
        self.skipped_slides = 0
        self.ocr_replaced = 0
        self.ocr_conf_sum = 0
        self.ocr_kept_graphic = 0
        self.quiz_options = 0
        #: Schriftarten des Kurses mit Häufigkeit (imc-Namen, vor der
        #: metrischen Ersetzung) — Grundlage der Schriften-Warnung.
        self.fonts: collections.Counter = collections.Counter()
        self.ocr_log: list[tuple] = []

    def build_slide(self, slide_src: dict, slide_hexname: str, idx: int):
        """-> (slide_xml, rels_xml, sld_guid, dur_ms, used_media_entries)."""
        shape_list: list[str] = []
        used: list[dict] = []
        dur = MIN_DUR

        if slide_src.get('exam'):
            return self._build_exam(slide_src, dur)

        items, audio = slide_content(slide_src['ata'])
        # Von imc gesetzte Standzeit der Folie. Ohne sie liefen Folien OHNE
        # Audio mit der pauschalen Mindestdauer, obwohl die echte Länge im
        # Kurs steht.
        dur = max(dur, slide_duration_ms(slide_src['ata']))
        zo = 0
        sid = 1

        # Kurs-Hintergrundbild als UNTERSTE Ebene (imc zeigt es hinter jeder
        # Folie; Folien mit eigenem Vollflächenbild überdecken es ohnehin).
        bg = self._build_background(zo, sid, dur, used)
        if bg:
            shape_list.append(bg)
            zo += 1
            sid += 1

        # Audio zuerst (bestimmt Dauer)
        if self.with_audio and audio:
            e = self.pool.add_audio(audio['bytes'], audio['name'])
            if e is None:
                self.skipped_audio += 1
                self.skipped_audio_log.append((idx, slide_src.get('name', '?'),
                                               self.pool.last_audio_error))
            else:
                used.append(e)
                if e['dur'] > 0:
                    dur = max(dur, e['dur'])
                shape_list.append(shapes.build_sound(self.tpl, e, dur, zo, sid))
                zo += 1
                sid += 1

        for _layer, kind, p in items:
            if kind == 'image':
                if self.ocr_text:
                    ob = ocr_textblocks(p['bytes'], p['rect'], rect_transform=self.rect_transform)
                    if ob:
                        boxes, _style, info = ob
                        # Steckt nennenswert Grafik NEBEN dem Text, bleibt das
                        # Bild erhalten (Textstellen ausgestempelt) — sonst
                        # verschwänden Diagramme/Screenshots mitsamt Beschriftung.
                        keep = self._keep_graphic(p, boxes, info)
                        if keep is not None:
                            e = self.pool.add_image(keep, p['name'])
                            if e is not None:
                                used.append(e)
                                shape_list.append(shapes.build_pic(
                                    self.tpl, e, p['rect'], p['name'], zo, sid, dur,
                                    p.get('opacity', 100),
                                    rect_transform=self.rect_transform))
                                zo += 1
                                sid += 1
                                self.ocr_kept_graphic += 1
                        # Je positionierter Box eine eigene Textbox mit ihrem
                        # Sub-Rect (imc-Koordinaten; Transform in build_textbox).
                        for box in boxes:
                            shape_list.append(shapes.build_textbox(
                                self.tpl, box['blocks'], box['rect'], 'left', zo, sid,
                                atsrect=True, rect_transform=self.rect_transform,
                                name=p.get('name') or 'Text'))
                            zo += 1
                            sid += 1
                        self.ocr_replaced += 1
                        self.ocr_conf_sum += info['conf']
                        self.ocr_log.append((slide_src.get('name', '?'), info['conf'], info['chars']))
                        continue
                # Deckkraft wird IN das Bild gerechnet (Storylines picFormat/
                # trans-Skala ist in den Referenzdateien unbelegt).
                raw = apply_opacity(p['bytes'], p.get('opacity', 100))
                e = self.pool.add_image(raw, p['name'])
                if e is None:
                    self.skipped_img += 1
                    self.skipped_img_log.append((idx, slide_src.get('name', '?'), p['name']))
                    continue
                used.append(e)
                shape_list.append(shapes.build_pic(
                    self.tpl, e, p['rect'], p['name'], zo, sid, dur,
                    p.get('opacity', 100), rect_transform=self.rect_transform,
                    rotation=p.get('rotation', 0)))
                zo += 1
                sid += 1
            elif kind == 'choices':
                shape_list.append(shapes.build_textbox(
                    self.tpl, self._choice_blocks(p), p['rect'], 'left', zo, sid,
                    atsrect=True, rect_transform=self.rect_transform,
                    name=p.get('name') or 'Antworten'))
                zo += 1
                sid += 1
                self.quiz_options += len(p['options'])
            elif kind == 'text':
                self.fonts[(p['elem'].get('fontFamily') or 'Arial').strip()] += 1
                blocks = parse_richtext(p['rich'], p['elem'], font_pt=self.geom.font_pt)
                shape_list.append(shapes.build_textbox(
                    self.tpl, blocks, p['rect'], p['align'], zo, sid,
                    atsrect=True, rect_transform=self.rect_transform,
                    name=p.get('name') or 'Text',
                    rotation=p.get('rotation', 0),
                    line_height=p.get('line_height'),
                    fill=p.get('fill'), stroke=p.get('stroke'),
                    opacity=p.get('opacity', 100)))
                zo += 1
                sid += 1

        sld = shapes.assemble_slide(self.tpl, shape_list, slide_src['name'], dur)
        rel_entries = self._dedup(used)
        rels = shapes.build_rels(rel_entries)
        g = re.search(r'<sld\b[^>]*\sg="([0-9a-fA-F-]{36})"', sld).group(1)
        return sld, rels, g, dur, rel_entries

    #: Markierung der Antwortoptionen im erzeugten Text.
    _MARK_RIGHT, _MARK_WRONG = '●', '○'      # ● / ○

    def _choice_blocks(self, item: dict) -> list[list]:
        """Antwortoptionen einer Interaktion -> Blöcke für eine Textbox.

        Storyline-Quizfragen lassen sich aus dem Gerüst heraus nicht erzeugen
        (es enthält keine Quiz-Schablonen, und ``strip_quiz`` entfernt den
        ``quizMgr``). Statt die Frage zu verlieren, landen Fragetext und
        Optionen als EDITIERBARER Text auf der Folie — die richtige Antwort
        fett und mit ● markiert. Damit ist die Frage in Storyline nachbaubar,
        ohne im Quellkurs zu suchen.
        """
        # Eigene Größe der Interaktion, sonst die Player-Vorgabe: im
        # imc-Rendering einer Frageseite nachgemessen ~25 px (Zeilenhöhe 30 px
        # bei 57 px Zeilenabstand).
        px = item.get('font_px') or 0
        pt = self.geom.font_pt(px if px > 0 else _CHOICE_DEFAULT_PX)
        base = dict(fam='Arial', size=pt, color='#000000',
                    bold=False, ital=False, under=False)
        blocks: list[list] = []
        if item.get('prompt'):
            blocks.append([(item['prompt'], dict(base, bold=True))])
        for text, correct in item['options']:
            mark = self._MARK_RIGHT if correct else self._MARK_WRONG
            blocks.append([(f'{mark} {text}', dict(base, bold=bool(correct)))])
        if item.get('kind') == 'draganddrop':
            blocks.append([('(Zuordnungsaufgabe — Ziele in Storyline zuweisen)',
                            dict(base, ital=True, color='#777777'))])
        return blocks

    def _keep_graphic(self, item: dict, boxes: list[dict], info: dict) -> bytes | None:
        """Bild als Grafik behalten? -> PNG-Bytes mit ausgestempeltem Text, sonst None.

        Entscheidungsgrundlage ist ``info['nontext']``: der Anteil der Bild-
        „Tinte", der außerhalb der erkannten Textkästen liegt. Unterhalb von
        :data:`~ats2story.ocr.imagemask.NONTEXT_KEEP_RATIO` ist das Bild
        praktisch reiner Text und wird wie bisher komplett durch Textboxen
        ersetzt.
        """
        if float(info.get('nontext', 0.0)) < NONTEXT_KEEP_RATIO:
            return None
        bboxes = [b.get('bbox_px') for b in boxes if b.get('bbox_px')]
        if not bboxes:
            return None
        return erase_text_regions(item['bytes'], bboxes, float(info.get('scale', 1.0)))

    def _build_background(self, zo: int, sid: int, dur: int, used: list[dict]) -> str | None:
        """Kurs-Hintergrundbild als ganzflächiges <pic> (oder None).

        Das Bild liegt einmal im Medienpool (md5-dedupliziert) und wird auf den
        vollen imc-Canvas gelegt — im Gegensatz zum Vorlagen-Hintergrund ist es
        damit in Storyline auswähl- und löschbar.
        """
        raw = self.background.get('image')
        if not raw:
            return None
        e = self.pool.add_image(raw, self.background.get('name') or 'Hintergrund')
        if e is None:
            return None
        used.append(e)
        self.bg_added += 1
        return shapes.build_pic(
            self.tpl, e, (0, 0, self.geom.ats_w, self.geom.ats_h),
            self.background.get('name') or 'Hintergrund', zo, sid, dur,
            100, rect_transform=self.rect_transform)

    def _build_exam(self, slide_src: dict, dur: int):
        """Test-Platzhalter-Folie."""
        # Platzhaltertext liegt in STORYLINE-Koordinaten (atsrect=False), die
        # Punktgrößen sind daher direkt gültig und brauchen keine Umrechnung.
        total = int(slide_src.get('q_total') or 0)
        new = int(slide_src.get('q_new') or 0)
        if not total:
            hint = 'Keine Fragen im Kurs auflösbar — in Storyline-Quiz nachbauen.'
        elif self.quiz_bank:
            hint = (f'{total} Frage(n) liegen in der Fragenbank dieser .story — '
                    'in Storyline unter Start › Fragenbanken › Fragenbanken '
                    'verwalten.')
        elif self.quiz_slides:
            reused = total - new
            hint = (f'{total} Frage(n) — als eigene Folien im Kurs enthalten'
                    + (f'; {reused} davon bereits weiter oben (mehrfach genutzt).'
                       if reused else '.'))
        elif self.quiz_export:
            # Der Normalfall: die Fragen liegen NEBEN der .story als
            # Importdatei. Stand hier vorher „als eigene Folien enthalten",
            # suchte man sie vergeblich im Kurs.
            hint = (f'{total} Frage(n) liegen in der Fragen-Datei neben dieser '
                    '.story — in Storyline über Datei › Import › Fragen aus '
                    'Datei einlesen.')
        else:
            hint = (f'{total} Frage(n) im Kurs — beim Export weder als Folien '
                    'noch als Datei angefordert.')
        # „[ TEST ]" gehört vor eine imc-Prüfung. Die Hinweisfolie eines
        # reinen Fragenkurses ist keine Prüfung — sie sagt nur, wo die Fragen
        # liegen, und trägt deshalb keine Warnfarbe.
        info = bool(slide_src.get('info'))
        head = slide_src['name'] if info else f'[ TEST ]  {slide_src["name"]}'
        blocks = [
            [(head, dict(
                fam='Arial', size='28', color=('#1F5FA8' if info else '#CC0000'),
                bold=True, ital=False, under=False))],
            [(hint, dict(
                fam='Arial', size='18', color='#444444', bold=False, ital=False, under=False))],
        ]
        # Sichtbares SLD-Rechteck als (L, T, R, B) — atsrect=False, also direkte
        # Storyline-Koordinaten, canvas-relativ zur jeweiligen Story-Size (bei
        # 'native' ist das der erkannte imc-Canvas). (Fix: Monolith übergab
        # (160,300,960,140), was als L,T,R,B B<T ergab -> unsichtbares Rechteck.)
        sw, sh = self.geom.story_w, self.geom.story_h
        rect = (sw * 0.125, sh * 0.2, sw * 0.875, sh * 0.8)
        tb = shapes.build_textbox(self.tpl, blocks, rect, 'center', 0, 1)
        sld = shapes.assemble_slide(self.tpl, [tb], slide_src['name'], dur)
        rels = shapes.build_rels([])
        g = re.search(r'<sld\b[^>]*\sg="([0-9a-fA-F-]{36})"', sld).group(1)
        return sld, rels, g, dur, []

    @staticmethod
    def _dedup(used: list[dict]) -> list[dict]:
        """Media-Entries nach fname deduplizieren (Reihenfolge erhalten)."""
        seen: set[str] = set()
        out: list[dict] = []
        for e in used:
            if e['fname'] in seen:
                continue
            seen.add(e['fname'])
            out.append(e)
        return out
