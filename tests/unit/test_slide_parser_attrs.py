#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide_parser: disabled-Filter, Füllung/Rahmen, Kurs-Hintergrund, Walker."""
from __future__ import annotations

import io
import zipfile

from ats2story.ats_reader import (
    course_background,
    slide_content,
    slide_duration_ms,
    walk_course,
)
from ats2story.ats_reader.slide_parser import fill_of, is_disabled, stroke_of

NS = 'http://im-c.de/xml/authoring/1.0'


def _ata(body: str, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('document/document.xml',
                   f'<?xml version="1.0"?><document xmlns="{NS}">{body}</document>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


_RECT = '<complexproperty name="rect"><rect x="10" y="20" width="30" height="40"/></complexproperty>'


def test_disabled_elements_are_skipped() -> None:
    """disabled="true" ist im imc-Player unsichtbar — und darf nicht in die .story."""
    body = (
        f'<text disabled="true" richText="&lt;p&gt;weg&lt;/p&gt;" layer="1">{_RECT}</text>'
        f'<text disabled="false" richText="&lt;p&gt;bleibt&lt;/p&gt;" layer="2">{_RECT}</text>')
    items, _audio = slide_content(_ata(body))
    assert [p['rich'] for _l, k, p in items if k == 'text'] == ['<p>bleibt</p>']


def test_disabled_image_and_audio_are_skipped() -> None:
    img = ('<image disabled="true" layer="1">'
           '<complexproperty name="image"><resource path="res/a.png"/></complexproperty>'
           f'{_RECT}</image>')
    au = ('<audiotrack disabled="true"><audio><complexproperty name="audio">'
          '<resource path="res/a.mp3"/></complexproperty></audio></audiotrack>')
    items, audio = slide_content(_ata(img + au, {'res/a.png': b'x', 'res/a.mp3': b'y'}))
    assert items == []
    assert audio is None


def test_text_carries_rotation_opacity_and_line_height() -> None:
    body = (f'<text richText="&lt;p&gt;x&lt;/p&gt;" layer="1" rotation="15" '
            f'opacity="60" lineHeight="125">{_RECT}</text>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert p['rotation'] == 15
    assert p['opacity'] == 60
    assert p['line_height'] == 125


def test_fill_and_stroke_are_read() -> None:
    body = (
        f'<text richText="&lt;p&gt;x&lt;/p&gt;" layer="1">{_RECT}'
        '<complexproperty name="fill"><fill style="1">'
        '<color color="#ffcc0000"/></fill></complexproperty>'
        '<complexproperty name="stroke"><stroke style="1" width="3"><fill style="1">'
        '<color color="#ff003366"/></fill></stroke></complexproperty>'
        '</text>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert p['fill'] == '#CC0000'
    assert p['stroke'] == ('#003366', 3.0)


def test_fill_style_zero_means_no_fill() -> None:
    body = (f'<text richText="&lt;p&gt;x&lt;/p&gt;" layer="1">{_RECT}'
            '<complexproperty name="fill"><fill style="0"/></complexproperty></text>')
    items, _ = slide_content(_ata(body))
    assert items[0][2]['fill'] is None


def test_helpers_on_plain_elements() -> None:
    class E:
        def __init__(self, **a):
            self._a = a

        def get(self, k, d=None):
            return self._a.get(k, d)

        def findall(self, _tag):
            return []

    assert is_disabled(E(disabled='true')) is True
    assert is_disabled(E(disabled='false')) is False
    assert is_disabled(E()) is False
    assert fill_of(E()) is None
    assert stroke_of(E()) is None


# ---- Kurs-Hintergrund / Walker --------------------------------------------

def _ats(doc_body: str, extra: dict | None = None) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('document/document.xml',
                   f'<?xml version="1.0"?><document xmlns="{NS}" '
                   f'backgroundColor="#FFFFFF">{doc_body}</document>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_course_background_reads_image_and_color() -> None:
    body = ('<complexproperty name="backgroundImage">'
            '<resource path="resources/jpg/bg.jpg" originalName="backgr.jpg"/>'
            '</complexproperty>')
    bg = course_background(_ats(body, {'resources/jpg/bg.jpg': b'JPEGDATA'}))
    assert bg['image'] == b'JPEGDATA'
    assert bg['name'] == 'backgr.jpg'
    assert bg['color'] == '#FFFFFF'


def test_course_background_without_image() -> None:
    bg = course_background(_ats(''))
    assert bg['image'] is None
    assert bg['color'] == '#FFFFFF'


def test_walker_keeps_slides_next_to_subfolders() -> None:
    """Folien, die NEBEN Unterordnern liegen, fielen früher ersatzlos weg."""
    ata = 'resources/ata/a.ata'
    body = (
        '<folder name="Kapitel">'
        f'<animation name="Direkt"><complexproperty name="content">'
        f'<resource path="{ata}"/></complexproperty></animation>'
        '<folder name="Unterkapitel">'
        f'<animation name="Tief"><complexproperty name="content">'
        f'<resource path="{ata}"/></complexproperty></animation>'
        '</folder></folder>')
    scenes = walk_course(_ats(body, {ata: _ata('')}))
    namen = {sc['name']: [s['name'] for s in sc['slides']] for sc in scenes}
    assert namen == {'Kapitel': ['Direkt'], 'Unterkapitel': ['Tief']}


# ---- Foliendauer -----------------------------------------------------------

def test_slide_duration_is_tenths_of_a_second() -> None:
    """``document@duration`` zählt Zehntelsekunden.

    Empirisch bestimmt: über die 11 Folien des PL-Kurses verhält sich die Länge
    der hinterlegten Sprecheraufnahme zum Attribut wie 100,7 : 1.
    """
    assert slide_duration_ms(_ata_with_duration('868')) == 86800
    assert slide_duration_ms(_ata_with_duration('71')) == 7100


def test_slide_duration_rejects_implausible_values() -> None:
    assert slide_duration_ms(_ata_with_duration('0')) == 0
    assert slide_duration_ms(_ata_with_duration('-5')) == 0
    assert slide_duration_ms(_ata_with_duration('99999999')) == 0
    assert slide_duration_ms(_ata_with_duration('kaputt')) == 0
    assert slide_duration_ms(_ata('')) == 0            # Attribut fehlt
    assert slide_duration_ms(b'kein zip') == 0


def _ata_with_duration(value: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('document/document.xml',
                   f'<?xml version="1.0"?><document xmlns="{NS}" '
                   f'duration="{value}"></document>')
    return buf.getvalue()


# ---- Quizfragen (.ati) ------------------------------------------------------

_POS = ('<complexproperty name="position"><point x="103" y="363"/></complexproperty>')


def test_singlechoice_options_and_correct_index() -> None:
    body = (f'<singlechoiceinteraction layer="13" width="812" height="118" '
            f'correctIndex="1" fontSize="-1">{_POS}'
            '<singlechoice text="Richtig."/><singlechoice text="Falsch."/>'
            '</singlechoiceinteraction>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert items[0][1] == 'choices'
    assert p['kind'] == 'single'
    assert p['options'] == [('Richtig.', False), ('Falsch.', True)]
    assert p['rect'] == (103.0, 363.0, 812.0, 118.0)
    assert p['font_px'] == -1                 # Player-Vorgabe


def test_multiplechoice_uses_checked_attribute() -> None:
    body = (f'<multiplechoiceinteraction layer="1" width="800" height="400">{_POS}'
            '<multiplechoice text="Presence" checked="false"/>'
            '<multiplechoice text="Place" checked="true"/>'
            '<multiplechoice text="Promotion" checked="true"/>'
            '</multiplechoiceinteraction>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert p['kind'] == 'multiple'
    assert p['options'] == [('Presence', False), ('Place', True), ('Promotion', True)]


def test_draganddrop_keeps_source_labels() -> None:
    """Quellen ohne Ablageziel (und ohne referenceId) gehen nicht verloren."""
    body = ('<draganddropinteraction layer="1">'
            '<dragsource text="Zweiter Schritt"/>'
            '<dragsource text="Dritter Schritt"/><droptarget/>'
            '</draganddropinteraction>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert p['kind'] == 'draganddrop'
    assert [t for t, _ok in p['options']] == ['Zweiter Schritt', 'Dritter Schritt']


def test_draganddrop_solution_order_comes_from_targets() -> None:
    """Die LÖSUNG steckt in den Ablagezielen, nicht in der Quellreihenfolge.

    Jedes <droptarget> verweist per <dragsourcereference> auf die richtige
    Quelle; die Reihenfolge ergibt sich aus der Position der Ziele (oben nach
    unten). Die <dragsource>-Folge ist nur die gemischte Anzeigereihenfolge.
    """
    def src(ref, text):
        return f'<dragsource referenceId="{ref}" text="{text}"/>'

    def tgt(ref, y):
        return (f'<droptarget><complexproperty name="position">'
                f'<point x="140" y="{y}"/></complexproperty>'
                f'<dragsourcereference referenceId="{ref}"/></droptarget>')

    body = ('<draganddropinteraction layer="1">'
            + src('{a}', 'Zweitens') + src('{b}', 'Erstens') + src('{c}', 'Drittens')
            + tgt('{b}', 100) + tgt('{a}', 200) + tgt('{c}', 300)
            + '</draganddropinteraction>')
    items, _ = slide_content(_ata(body))
    p = items[0][2]
    assert [t for t, _ok in p['options']] == ['Erstens', 'Zweitens', 'Drittens']
    assert all(ok for _t, ok in p['options'])


def test_disabled_interaction_is_skipped() -> None:
    body = (f'<singlechoiceinteraction disabled="true" correctIndex="0">{_POS}'
            '<singlechoice text="A"/></singlechoiceinteraction>')
    items, _ = slide_content(_ata(body))
    assert items == []


def test_walker_resolves_exam_questions_from_vault_once() -> None:
    """Fragen liegen im <vault>, nicht im Kapitelbaum — und dieselbe Frage wird
    von mehreren Tests genutzt; ausgegeben wird sie genau EINMAL."""
    ati = 'resources/ati/q1.ati'
    ref = '{4420bf61-3dfc-48f5-acfd-655fcab3721d}'
    pool = (f'<vault><folder name="Pool" referenceId="{ref}">'
            f'<interaction name="Frage 1"><complexproperty name="content">'
            f'<resource path="{ati}"/></complexproperty></interaction>'
            '</folder></vault>')

    def exam(name: str) -> str:
        return (f'<exam name="{name}"><questionpoolcollection>'
                f'<folderpool referenceId="{ref}"/></questionpoolcollection></exam>')

    body = '<folder name="Kapitel">' + exam('Test A') + exam('Test B') + '</folder>' + pool
    scenes = walk_course(_ats(body, {ati: _ata('')}))
    slides = [s for sc in scenes for s in sc['slides']]
    assert [s['name'] for s in slides] == ['Test A', 'Frage 1', 'Test B']
    assert slides[0]['q_total'] == 1 and slides[0]['q_new'] == 1
    assert slides[2]['q_total'] == 1 and slides[2]['q_new'] == 0   # schon ausgegeben
    assert slides[1]['quiz'] is True


def test_walker_emits_vault_questions_no_exam_references() -> None:
    """Der Fragenpool enthält mehr Fragen, als die Prüfungen ziehen.

    Im Kurs „Kurs A" liegen 45 Fragen im <vault>, die einzige
    Prüfung referenziert 5. Der imc-Publisher exportiert laut seinem Protokoll
    trotzdem ALLE, gruppiert nach den Vault-Ordnern. Ohne diesen Schritt gingen
    dort 40 von 45 Fragen verloren.
    """
    ati = 'resources/ati/q%d.ati'
    ref = '{f41b27ed-0f5e-4ea9-a1a4-41b805c18abf}'

    def inter(i: int) -> str:
        return (f'<interaction name="Frage {i}"><complexproperty name="content">'
                f'<resource path="{ati % i}"/></complexproperty></interaction>')

    vault = ('<vault><folder name="Classic">'
             f'<folder name="Kurs A" referenceId="{ref}">{inter(1)}</folder>'
             f'<folder name="Phasen">{inter(2)}{inter(3)}</folder>'
             '</folder></vault>')
    exam = (f'<exam name="Test"><questionpoolcollection>'
            f'<folderpool referenceId="{ref}"/></questionpoolcollection></exam>')
    body = f'<folder name="Kapitel">{exam}</folder>{vault}'
    extra = {ati % i: _ata('') for i in (1, 2, 3)}

    scenes = walk_course(_ats(body, extra))
    namen = {sc['name']: [s['name'] for s in sc['slides']] for sc in scenes}
    # Frage 1 hängt an ihrer Prüfung, 2+3 kommen als eigene Vault-Szene.
    assert namen['Kapitel'] == ['Test', 'Frage 1']
    assert namen['Classic / Phasen'] == ['Frage 2', 'Frage 3']
    # Keine Frage doppelt:
    alle = [n for v in namen.values() for n in v if n.startswith('Frage')]
    assert sorted(alle) == ['Frage 1', 'Frage 2', 'Frage 3']
