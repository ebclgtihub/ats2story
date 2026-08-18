#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quizfragen im Articulate-Importformat.

Storyline baut aus einer Excel-/Textdatei ECHTE Quizfolien. Format laut
Articulate: Fragetyp · Punkte · Fragetext · Antwortoptionen, richtige Antworten
mit vorangestelltem ``*``, ``//`` leitet Kommentare ein.
"""
from __future__ import annotations

import os
import zipfile

from ats2story.quiz_export import (
    DEFAULT_POINTS,
    MAX_CHOICES,
    _col,
    collect_questions,
    question_from_slide,
    write_text,
    write_xlsx,
)


def _items(kind, options, texts=(), prompt=''):
    out = [(1, 'choices', dict(kind=kind, options=list(options), prompt=prompt))]
    for i, t in enumerate(texts):
        out.append((i + 2, 'text', dict(rich=f'<p>{t}</p>')))
    return out


def test_single_choice_becomes_mc() -> None:
    q = question_from_slide('F1', _items('single', [('A', False), ('B', True), ('C', False)],
                                         texts=['Kopfzeile', 'Was ist die richtige Antwort?']))
    assert q['type'] == 'MC'
    assert q['points'] == DEFAULT_POINTS
    assert q['text'] == 'Was ist die richtige Antwort?'   # längster Text = Frage


def test_true_false_pair_becomes_tf() -> None:
    """Zwei Optionen „Richtig./Falsch." sind eine Wahr/Falsch-Frage."""
    q = question_from_slide('F', _items('single', [('Richtig.', True), ('Falsch.', False)],
                                        texts=['Aussage stimmt.']))
    assert q['type'] == 'TF'


def test_multiple_choice_becomes_mr() -> None:
    q = question_from_slide('F', _items('multiple', [('A', True), ('B', False), ('C', True)],
                                        texts=['Welche treffen zu?']))
    assert q['type'] == 'MR'
    assert [c for _t, c in q['options']] == [True, False, True]


def test_dragdrop_becomes_sequence() -> None:
    q = question_from_slide('F', _items('draganddrop', [('Erst', True), ('Dann', True)],
                                        texts=['Bringen Sie in die richtige Reihenfolge']))
    assert q['type'] == 'SD'


def test_question_text_skips_scene_header() -> None:
    """Die Kopfzeile trägt den Namen der Übung — sie ist nicht die Frage."""
    q = question_from_slide('F', _items('single', [('A', True)],
                                        texts=['Beispielfragen', 'Kurz?']),
                            scene='Beispielfragen')
    assert q['text'] == 'Kurz?'


def test_prompt_wins_over_slide_text() -> None:
    q = question_from_slide('F', _items('textgap', [('42', True)],
                                        texts=['Irgendein langer Fliesstext auf der Folie'],
                                        prompt='Wie viele Euro?'))
    assert q['type'] == 'FIB'
    assert q['text'] == 'Wie viele Euro?'


def test_no_interaction_gives_none() -> None:
    assert question_from_slide('F', [(1, 'text', dict(rich='<p>nur Text</p>'))]) is None
    assert question_from_slide('F', _items('single', [])) is None


def test_choices_are_capped() -> None:
    many = [(f'Option {i}', i == 0) for i in range(15)]
    q = question_from_slide('F', _items('single', many, texts=['Frage?']))
    assert len(q['options']) == MAX_CHOICES


def test_collect_skips_non_quiz_slides() -> None:
    def fake_content(ata):
        return _items('single', [('A', True), ('B', False)], texts=['Frage?']), None

    scenes = [dict(name='S', slides=[
        dict(name='Inhalt', ata=b'x'),                 # kein quiz -> übersprungen
        dict(name='Frage 1', ata=b'x', quiz=True),
        dict(name='Test', exam=True),                  # kein ata -> übersprungen
    ])]
    qs = collect_questions(scenes, fake_content)
    assert [q['slide'] for q in qs] == ['Frage 1']


# ---- Dateiformate ----------------------------------------------------------

def _sample():
    return [dict(type='MC', points=10, text='Frage A?', slide='F1', scene='S',
                 options=[('Eins', True), ('Zwei', False)]),
            dict(type='SD', points=10, text='Reihenfolge?', slide='F2', scene='S',
                 options=[('Erst', True), ('Dann', True)])]


def test_text_file_layout(tmp_path) -> None:
    """Jedes Feld in einer eigenen Zeile, Leerzeile zwischen den Fragen."""
    p = tmp_path / 'f.txt'
    assert write_text(_sample(), str(p)) == 2
    lines = p.read_text(encoding='utf-8-sig').splitlines()
    block = lines[lines.index('MC'):]
    assert block[:5] == ['MC', '10', 'Frage A?', '*Eins', 'Zwei']
    assert any(x.startswith('//') for x in lines)      # Kommentarzeilen erlaubt


def test_sequence_questions_carry_no_asterisk(tmp_path) -> None:
    """Bei Reihenfolgefragen zählt die Folge, nicht eine Markierung."""
    p = tmp_path / 'f.txt'
    write_text(_sample(), str(p))
    txt = p.read_text(encoding='utf-8-sig')
    assert '*Erst' not in txt and '\nErst' in txt


def test_xlsx_is_a_readable_workbook(tmp_path) -> None:
    p = tmp_path / 'f.xlsx'
    assert write_xlsx(_sample(), str(p)) == 2
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        assert {'[Content_Types].xml', 'xl/workbook.xml',
                'xl/worksheets/sheet1.xml'} <= names
        sheet = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
    assert '<c r="A2"' in sheet and 'MC' in sheet
    assert '*Eins' in sheet


def test_column_letters() -> None:
    assert [_col(i) for i in (0, 1, 25, 26, 27)] == ['A', 'B', 'Z', 'AA', 'AB']


def test_questions_survive_when_quiz_slides_are_off(tmp_path, fixture_ats, fixture_tpl) -> None:
    """Fragen dürfen NICHT aus der Importdatei fallen, nur weil sie keine
    Folien mehr werden.

    Der Konverter entfernt die Fragen standardmäßig aus der Folienliste (sie
    gehen als Importdatei heraus). Wird zu früh gefiltert, sammelt der Export
    nichts mehr ein — genau dieser Fehler war schon einmal drin.
    """
    import ats2story

    out = str(tmp_path / 'q.story')
    stats = ats2story.convert_ats(fixture_ats, out, tpl=fixture_tpl, no_audio=True,
                                  quiz_slides=False, progress=lambda f, m: None)
    files = stats['quiz_files']
    if not files:
        return                      # Fixture ohne Fragen — nichts zu prüfen
    assert any(f.endswith('.xlsx') for f in files)
    for path in files:
        assert os.path.getsize(path) > 0
    with zipfile.ZipFile(next(f for f in files if f.endswith('.xlsx'))) as z:
        sheet = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
    assert sheet.count('<row ') > 1, 'Importdatei enthält nur die Kopfzeile'


# --- Platzhaltertext der Prüfungsfolien -----------------------------------
# Er stand fest auf „als eigene Folien im Kurs enthalten". Im Normalfall gehen
# die Fragen aber in die Importdatei — wer dem Text folgte, suchte sie
# vergeblich im Kurs.
def _exam_hint(**kw) -> str:
    import re
    from ats2story.story_writer.builder import Builder

    class _Tpl:
        slide_skeleton = '<sld g="00000000-0000-0000-0000-000000000000" ' \
                         'verG="00000000-0000-0000-0000-000000000000" id="1" name="x">' \
                         '<tmProps min="0" />{SHAPES}</sld>'
        preserve: frozenset = frozenset()
        tb_stencil = ('<textBox id="1" name="Text" zOrder="0"><loc l="0" t="0" r="1" b="1" />'
                      '<text></text><fmtText></fmtText><str>00000000000</str></textBox>')

    b = Builder(_Tpl(), pool=None, **kw)
    sld, _rels, _g, _dur, _used = b._build_exam(
        dict(name='Test', q_total=5, q_new=5), 1000)
    import html as _h
    docs = re.findall(r'<text>(.*?)</text>', sld, re.S)
    return ' '.join(re.findall(r'Text="([^"]*)"', _h.unescape(''.join(docs))))


def test_exam_hint_points_to_the_import_file() -> None:
    """Normalfall: Fragen als Datei -> der Platzhalter muss dorthin zeigen."""
    txt = _exam_hint(quiz_slides=False, quiz_export=True)
    assert 'Fragen-Datei' in txt and 'Import' in txt
    assert 'als eigene Folien' not in txt


def test_exam_hint_points_into_the_course_when_slides_were_built() -> None:
    txt = _exam_hint(quiz_slides=True, quiz_export=False)
    assert 'als eigene Folien im Kurs enthalten' in txt


def test_exam_hint_when_questions_go_nowhere() -> None:
    txt = _exam_hint(quiz_slides=False, quiz_export=False)
    assert 'weder als Folien noch als Datei' in txt
