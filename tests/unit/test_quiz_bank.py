#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fragen aus dem imc-Depot als Storyline-Fragenbank."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from ats2story import quiz_bank as qb
from ats2story.geometry import extract_element

pytestmark = pytest.mark.skipif(not qb.available(), reason='Fragenbank-Vorlage fehlt')


@pytest.fixture(scope='module')
def tpl() -> qb.BankTemplate:
    return qb.BankTemplate()


def _q(qtype: str, opts: list[tuple[str, bool]], text: str = 'Fragetext?') -> dict:
    return dict(type=qtype, name='Frage', text=text, options=opts)


def _rows_of(xml: str, qtype: str) -> list[str]:
    return [f for _i, f in qb._rows(xml, qb.TEMPLATES[qtype][2])]


@pytest.mark.parametrize('qtype,count', [('MC', 2), ('MC', 6), ('MR', 3), ('MR', 8),
                                         ('TF', 2), ('SD', 4), ('SD', 5)])
def test_row_count_follows_the_question(tpl: qb.BankTemplate, qtype: str, count: int) -> None:
    """Die Vorlage hat 3 bzw. 5 Zeilen — eure Fragen haben 2 bis 8."""
    opts = [(f'Antwort {i}', i == 0) for i in range(count)]
    slide = qb.build_slide(tpl, _q(qtype, opts))
    assert slide is not None
    assert len(_rows_of(slide.xml, qtype)) == count


@pytest.mark.parametrize('qtype', ['MC', 'MR', 'TF', 'SD'])
def test_slide_is_well_formed(tpl: qb.BankTemplate, qtype: str) -> None:
    slide = qb.build_slide(tpl, _q(qtype, [('A', True), ('B', False), ('C', False), ('D', False)]))
    ET.fromstring(slide.xml.encode('utf-8'))


#: Die Antworttexte, die die Vorlage mitbringt — nach dem Bauen darf keiner
#: davon mehr in der Folie stehen, in KEINER Schreibweise.
_TEMPLATE_WORDS = ['Erstens', 'Zweitens', 'Drittens', 'erstens', 'zweitens', 'drittens',
                   'A', 'B', 'C', 'D', 'E']


@pytest.mark.parametrize('qtype', ['MC', 'MR', 'TF', 'SD'])
def test_answer_text_is_replaced_in_both_notations(tpl: qb.BankTemplate, qtype: str) -> None:
    """Jeder Antworttext steht zweifach: fünfmal als <plain>, einmal formatiert.

    Storyline ZEIGT und wertet den formatierten aus. Wurde nur <plain>
    ersetzt, stand in der fertigen Frage weiter „erstens" — und genau das war
    hier schon einmal kaputt, ohne dass ein Test es merkte.
    """
    opts = [(f'Antwort {i}', i == 0) for i in range(4)]
    slide = qb.build_slide(tpl, _q(qtype, opts))
    for word in _TEMPLATE_WORDS:
        assert f'<plain>{word}</plain>' not in slide.xml, f'{word} als <plain> übrig'
        assert f'Text="{word}"' not in slide.xml, f'{word} im formatierten Text übrig'
    for i in range(4):
        assert f'Text="Antwort {i}"' in slide.xml, f'Antwort {i} fehlt im formatierten Text'


def test_question_text_lands_in_the_formatted_title(tpl: qb.BankTemplate) -> None:
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)], text='Was gilt hier?'))
    assert 'Text="Was gilt hier?"' in slide.xml


def test_solution_lands_on_the_right_row(tpl: qb.BankTemplate) -> None:
    opts = [('A', False), ('B', True), ('C', False), ('D', True), ('E', False)]
    slide = qb.build_slide(tpl, _q('MR', opts))
    flags = [re.search(r'<scoreData\b[^>]*correct="(true|false)"', f).group(1)
             for f in _rows_of(slide.xml, 'MR')]
    assert flags == ['false', 'true', 'false', 'true', 'false']


def test_childlst_lists_exactly_the_rows(tpl: qb.BankTemplate) -> None:
    """Die Interaktion führt ihre Antworten als GUID-Liste.

    Blieb sie auf den drei Zeilen der Vorlage stehen, kannte die Frage die
    hinzugefügten Antworten nicht.
    """
    slide = qb.build_slide(tpl, _q('MR', [(f'A{i}', False) for i in range(7)]))
    intr_tag = qb.TEMPLATES['MR'][1]
    intr = extract_element(slide.xml, slide.xml.find('<' + intr_tag), intr_tag)
    listed = re.findall(r'<g>([0-9a-fA-F-]{36})</g>',
                        re.search(r'<childLst>(.*?)</childLst>', intr, re.S).group(1))
    rows = [re.search(r'\sg="([0-9a-fA-F-]{36})"', f).group(1) for f in _rows_of(slide.xml, 'MR')]
    assert listed == rows


def test_question_text_lands_in_the_title(tpl: qb.BankTemplate) -> None:
    slide = qb.build_slide(tpl, _q('MC', [('A', True), ('B', False)], text='Was gilt hier?'))
    boxes = [f for _i, f in qb._rows(slide.xml, 'textBox')]
    assert any('Was gilt hier?' in f for f in boxes)


def test_true_false_keeps_the_imc_wording(tpl: qb.BankTemplate) -> None:
    """Wahr/Falsch läuft über die Einfachauswahl — sonst würden „Richtig."/
    „Falsch." zu Storylines „True"/„False"."""
    slide = qb.build_slide(tpl, _q('TF', [('Richtig.', True), ('Falsch.', False)]))
    texts = [re.search(r'<plain>([^<]*)</plain>', f).group(1) for f in _rows_of(slide.xml, 'TF')]
    assert texts == ['Richtig.', 'Falsch.']


def test_every_slide_gets_its_own_guids(tpl: qb.BankTemplate) -> None:
    """Zwei Folien mit derselben Kennung sind für Storyline ein Widerspruch."""
    a = qb.build_slide(tpl, _q('MC', [('A', True), ('B', False)]))
    b = qb.build_slide(tpl, _q('MC', [('C', True), ('D', False)]))
    assert a.guid != b.guid
    ga = set(re.findall(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', a.xml))
    gb = set(re.findall(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', b.xml))
    shared = (ga & gb) - tpl.outside_guids - {qb.ZERO}
    assert shared == set(), f'geteilte GUIDs: {sorted(shared)[:3]}'


def test_unsupported_type_is_reported_not_dropped_silently(tpl: qb.BankTemplate) -> None:
    """Lückentext kann die Vorlage nicht — das muss auffallen, nicht verschwinden."""
    built, skipped = qb.build_bank([_q('FIB', [('Lösung', True)]),
                                    _q('MC', [('A', True), ('B', False)])])
    assert len(built) == 1
    assert skipped == {'FIB': 1}


def test_bank_scene_lists_every_slide(tpl: qb.BankTemplate) -> None:
    built, _ = qb.build_bank([_q('MC', [('A', True), ('B', False)]) for _ in range(3)])
    scene = qb.bank_scene_xml(built)
    ET.fromstring(scene.encode('utf-8'))
    assert len(re.findall(r'<sldId>', scene)) == 3


# --- Schriftgröße und mitwachsender Fragerahmen ----------------------------
# Die Vorlage hat für die Frage einen einzeiligen Streifen (44..122), gedacht
# für einen kurzen Titel. imc-Fragen sind ganze Aufgabenstellungen — im Median
# 121 bis 167 Zeichen, im längsten Fall 618.
def _title_box(xml: str) -> str:
    return qb._rows(xml, 'textBox')[0][1]


def _bounds(frag: str) -> tuple[float, float]:
    m = re.search(r'<loc\b[^>]*/>', frag)
    return (float(re.search(r't="([-\d.]+)"', m.group(0)).group(1)),
            float(re.search(r'b="([-\d.]+)"', m.group(0)).group(1)))


def test_short_question_keeps_the_template_box(tpl: qb.BankTemplate) -> None:
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)], text='Kurz?'))
    assert _bounds(_title_box(slide.xml)) == (qb._TITLE_TOP, qb._TITLE_MIN_BOTTOM)


def test_long_question_gets_a_taller_box(tpl: qb.BankTemplate) -> None:
    """In den Streifen gequetscht schrumpft Storyline lange Fragen auf
    Unleserlichkeit — der Rahmen muss mitwachsen."""
    lang = 'Wort ' * 60
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)], text=lang))
    _t, b = _bounds(_title_box(slide.xml))
    assert b > qb._TITLE_MIN_BOTTOM
    assert b <= qb._TITLE_MAX_BOTTOM


def test_answers_move_below_the_question(tpl: qb.BankTemplate) -> None:
    """Sonst lägen sie unter dem Fragetext."""
    lang = 'Wort ' * 60
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)], text=lang))
    _t, qbottom = _bounds(_title_box(slide.xml))
    intr = qb._rows(slide.xml, qb.TEMPLATES['MC'][1])[0][1]
    atop, _b = _bounds(intr)
    assert atop >= qbottom


@pytest.mark.parametrize('pt', [14.0, 18.5, 24.0])
def test_font_size_reaches_question_and_answers(tpl: qb.BankTemplate, pt: float) -> None:
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)]),
                           title_pt=pt, choice_pt=round(12.0 * pt / 18.5, 1))
    assert f'fontSz="{pt:g}"' in _title_box(slide.xml)
    row = qb._rows(slide.xml, 'radio')[0][1]
    assert re.search(r'fontSz="([\d.]+)"', row)


def test_question_font_size_is_written_out(tpl: qb.BankTemplate) -> None:
    """Der Frage-Rahmen ist ein Titel-Platzhalter.

    Der Wert in ``<resize fontSz>`` ist nur Storylines Merkposten — angewendet
    wird die Themenschrift (32 pt). Ohne ausgeschriebene Größe stand die Frage
    riesig und einzeilig über den Rand hinaus.
    """
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)],
                                   text='Kurze Frage?'), title_pt=18.5)
    box = qb._rows(slide.xml, 'textBox')[0][1]
    doc = __import__('html').unescape(re.search(r'<text>(.*?)</text>', box, re.S).group(1))
    assert 'FontSize="18.5"' in doc
    assert f'FontFamily="{qb.TITLE_FONT}"' in doc


@pytest.mark.parametrize('pt', [14.0, 24.0])
def test_chosen_size_reaches_the_document(tpl: qb.BankTemplate, pt: float) -> None:
    slide = qb.build_slide(tpl, _q('MC', [('A1', True), ('B1', False)]), title_pt=pt)
    box = qb._rows(slide.xml, 'textBox')[0][1]
    doc = __import__('html').unescape(re.search(r'<text>(.*?)</text>', box, re.S).group(1))
    assert f'FontSize="{pt:g}"' in doc


# --- Text darf die Folie nicht verlassen -----------------------------------
def _head(frag: str) -> str:
    return frag[:frag.index('>') + 1]


@pytest.mark.parametrize('qtype', ['MC', 'MR', 'TF', 'SD'])
def test_question_and_answers_wrap(tpl: qb.BankTemplate, qtype: str) -> None:
    """Die Vorlage steht auf wrap="none" — für den kurzen Titel „Multiple
    Choice" gedacht. Eine imc-Aufgabenstellung lief damit einzeilig aus der
    Folie heraus; die längsten Antworten liegen weit über 200 Zeichen."""
    lang = 'Ein sehr langer Text, ' * 12
    slide = qb.build_slide(tpl, _q(qtype, [(lang, True), ('Kurz', False)], text=lang))
    box = qb._rows(slide.xml, 'textBox')[0][1]
    assert 'wrap="true"' in _head(box)
    assert 'autoFit="resize"' in _head(box)
    row = qb._rows(slide.xml, qb.TEMPLATES[qtype][2])[0][1]
    assert 'wrap="true"' in _head(row)
    assert 'autoFit="resize"' in _head(row)


def test_no_unwrapped_state_survives_in_a_row(tpl: qb.BankTemplate) -> None:
    """Eine Antwort liegt fünffach in ihrer Form (Normal, Ausgewählt,
    Rückblick …). Bliebe dort wrap="none", liefe der Text in der
    Auswertungsansicht wieder aus der Folie."""
    slide = qb.build_slide(tpl, _q('MR', [('Sehr lange Antwort ' * 8, True), ('Kurz', False)]))
    for tag in ('checkBox', 'textBox'):
        for _pos, frag in qb._rows(slide.xml, tag):
            assert 'wrap="none"' not in frag


# --- Fragen dürfen nie verschwinden ---------------------------------------
def test_missing_template_falls_back_to_the_import_file(tmp_path, monkeypatch) -> None:
    """Fehlt die Vorlage, gibt es keine Bank — und ohne Rückfall wären die
    Fragen NIRGENDS, weil der Excel-Export standardmäßig aus ist. Genau so
    entstand eine .story ohne eine einzige Frage.

    Geprüft am echten Kurs, sofern einer vorliegt; sonst übersprungen.
    """
    import glob
    import os

    from ats2story import converter, quiz_bank as qbmod

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ats = sorted(glob.glob(os.path.join(root, '*.ats')), key=os.path.getsize)
    ats = ats or sorted(glob.glob(os.path.expanduser('~/Downloads/*.ats')), key=os.path.getsize)
    if not ats:
        pytest.skip('kein .ats zum Gegenprüfen vorhanden')

    # Einen Kurs nehmen, der überhaupt Fragen hat — sonst prüft der Test
    # nichts (der kleinste im Projektverzeichnis hat keine).
    import zipfile

    import ats2story
    from ats2story.ats_reader.slide_parser import slide_content
    from ats2story.quiz_export import collect_questions

    src = None
    for cand in ats:
        with zipfile.ZipFile(cand) as z:
            if collect_questions(ats2story.walk_course(z), slide_content):
                src = cand
                break
    if src is None:
        pytest.skip('kein .ats mit Fragen vorhanden')

    monkeypatch.setattr(qbmod, 'ASSET', str(tmp_path / 'gibt-es-nicht.story'))
    assert not qbmod.available()

    out = str(tmp_path / 'k.story')
    # max_slides=1: geprüft wird der Weg der FRAGEN, nicht das Bauen der
    # Folien — ohne die Bremse läuft der Test über eine Minute.
    stats = converter.convert_ats(src, out, quiz_bank=True, quiz_export=False,
                                  max_slides=1, progress=lambda *_a: None)
    assert stats['bank_slides'] == 0
    # ... aber die Fragen sind trotzdem da:
    assert stats['quiz_files'], 'Fragen sind spurlos verschwunden'
    assert any(f.endswith('.xlsx') for f in stats['quiz_files'])


def test_question_only_course_still_has_a_scene(tmp_path) -> None:
    """Ein reiner Prüfungskurs besteht nur aus Fragen.

    Nach dem Aussortieren der Frage- und Platzhalterfolien blieb NICHTS übrig:
    eine .story ohne eine einzige Szene, deren Startverweis zudem auf eine
    Szene der Vorlage zeigte, die es nicht mehr gab.
    """
    import glob
    import os
    import re
    import zipfile

    import ats2story
    from ats2story.ats_reader.slide_parser import slide_content
    from ats2story.quiz_export import collect_questions

    cands = sorted(glob.glob(os.path.expanduser('~/Downloads/*.ats')), key=os.path.getsize)
    src = None
    for cand in cands:
        with zipfile.ZipFile(cand) as z:
            scenes = ats2story.walk_course(z)
        if collect_questions(scenes, slide_content) and not [
                s for sc in scenes for s in sc['slides']
                if not s.get('quiz') and not s.get('exam')]:
            src = cand
            break
    if src is None:
        pytest.skip('kein Kurs ohne Inhaltsfolien vorhanden')

    out = str(tmp_path / 'k.story')
    ats2story.convert_ats(src, out, no_exams=True, quiz_bank=True,
                          progress=lambda *_a: None)
    with zipfile.ZipFile(out) as z:
        story = z.read('story/story.xml').decode('utf-8', 'replace')
    scenes_xml = re.search(r'<sceneLst>(.*?)</sceneLst>', story, re.S).group(1)
    assert re.findall(r'<scene\b', scenes_xml), 'Datei ohne jede Szene'
    pg = re.search(r'<story\b[^>]*\spG="([0-9a-fA-F-]{36})"', story).group(1)
    assert pg in scenes_xml, 'Startverweis zeigt auf eine Szene, die es nicht gibt'
