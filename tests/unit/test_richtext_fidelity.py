#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""richText-Treue: Zeilenumbrüche, CSS-Resets, Unterstreichung, px->pt."""
from __future__ import annotations

import pytest

from ats2story.geometry import Geometry
from ats2story.richtext import (
    fmt_document,
    fmt_line_spacing,
    fmt_size,
    map_font,
    parse_richtext,
)


class Elem:
    """Minimales .ata-Textelement (nur ``.get``)."""

    def __init__(self, **attrs) -> None:
        self._a = attrs

    def get(self, key, default=None):
        return self._a.get(key, default)


def test_br_starts_a_new_block() -> None:
    """<br> war ein Leerzeichen — der Umbruch ging verloren.

    Storyline hat keinen weichen Zeilenumbruch (in einer Storyline-eigenen
    Datei: kein Steuerzeichen in ``<Span Text>``, kein ``<Br>``-Tag), jede
    Zeile ist ein eigener Block. Genau so wird ``<br>`` abgebildet.
    """
    blocks = parse_richtext('<p>Zeile eins<br/>Zeile zwei</p>', Elem())
    assert len(blocks) == 2
    assert ''.join(t for t, _ in blocks[0]) == 'Zeile eins'
    assert ''.join(t for t, _ in blocks[1]) == 'Zeile zwei'


def test_br_keeps_span_formatting_across_the_break() -> None:
    """Ein <br> INNERHALB eines <span> darf dessen Formatierung nicht verlieren."""
    css = 'font-weight: bold;color: #FF0000;'
    blocks = parse_richtext(f'<p><span style="{css}">oben<br/>unten</span></p>', Elem())
    assert len(blocks) == 2
    for blk in blocks:
        assert blk[0][1]['bold'] is True
        assert blk[0][1]['color'] == '#FF0000'


def test_multiple_br_produce_empty_blocks() -> None:
    blocks = parse_richtext('<p>a<br/><br/>b</p>', Elem())
    assert [''.join(t for t, _ in b) for b in blocks] == ['a', '', 'b']


def test_span_normal_resets_element_bold_and_italic() -> None:
    """imc schreibt 'font-weight: normal' — das muss fett/kursiv aufheben."""
    el = Elem(fontBold='true', fontItalic='true', fontUnderline='true')
    css = 'font-weight: normal;font-style: normal;text-decoration: none;'
    blocks = parse_richtext(f'<p><span style="{css}">Text</span></p>', el)
    style = blocks[0][0][1]
    assert style['bold'] is False
    assert style['ital'] is False
    assert style['under'] is False


def test_span_sets_bold_italic_underline() -> None:
    css = 'font-weight: bold;font-style: italic;text-decoration: underline;'
    blocks = parse_richtext(f'<p><span style="{css}">Text</span></p>', Elem())
    style = blocks[0][0][1]
    assert (style['bold'], style['ital'], style['under']) == (True, True, True)


def test_span_font_family_and_color() -> None:
    """Arimo wird auf sein metrisches Gegenstück Arial abgebildet — auf einem
    Storyline-Rechner ist Arimo praktisch nie installiert, und eine beliebige
    Ersatzschrift hätte andere Zeichenbreiten (der Umbruch verschiebt sich)."""
    css = 'font-family: Arimo, sans-serif;color: #C7D9E7;'
    blocks = parse_richtext(f'<p><span style="{css}">Text</span></p>', Elem())
    style = blocks[0][0][1]
    assert style['fam'] == 'Arial'
    assert style['color'] == '#C7D9E7'


def test_unknown_font_is_left_alone() -> None:
    """Ersetzt wird NUR, was nachweislich zeichenbreitengleich ist."""
    assert map_font('Segoe Print') == 'Segoe Print'
    assert map_font('  Arimo  ') == 'Arial'
    assert map_font('LIBERATION SERIF') == 'Times New Roman'
    assert map_font(None) == 'Arial'
    assert map_font('') == 'Arial'


def test_element_font_family_is_mapped() -> None:
    blocks = parse_richtext('<p>Text</p>', Elem(fontFamily='Arimo'))
    assert blocks[0][0][1]['fam'] == 'Arial'


def test_font_size_from_element_and_span_are_converted() -> None:
    """Element-fontSize UND span-font-size sind px und werden umgerechnet."""
    g = Geometry('native', 1024, 748)          # Faktor 1.0 -> reine px->pt-Umrechnung
    blocks = parse_richtext(
        '<p><span style="font-size: 21px;">Gross</span></p>',
        Elem(fontSize='24'), font_pt=g.font_pt)
    assert blocks[0][0][1]['size'] == pytest.approx(21 * 0.75, abs=0.06)

    plain = parse_richtext('<p>Basis</p>', Elem(fontSize='24'), font_pt=g.font_pt)
    assert plain[0][0][1]['size'] == pytest.approx(24 * 0.75, abs=0.05)


def test_without_font_pt_size_is_unchanged() -> None:
    """Alt-Aufrufer ohne Geometrie bekommen weiterhin den Rohwert."""
    blocks = parse_richtext('<p>x</p>', Elem(fontSize='24'))
    assert blocks[0][0][1]['size'] == '24'


def test_line_spacing_maps_imc_percent_to_absolute_points() -> None:
    """imc rechnet CSS-artig: Zeilenabstand = Schriftgröße x lineHeight.

    Im imc-Rendering des Beispielkurses nachgemessen: fontSize 13, lineHeight
    125 -> 16 px Abstand (= 13 x 1,25). Storylines 'Multiple' bezieht sich
    dagegen auf dessen EIGENEN einfachen Abstand (bereits ~1,2 em) und würde
    doppelt zählen — deshalb 'Exactly' in Punkt.
    """
    assert fmt_line_spacing(125, 9.8) == ('Exactly', '12.25')
    assert fmt_line_spacing(125, 13.5) == ('Exactly', '16.88')
    assert fmt_line_spacing(150, 10) == ('Exactly', '15')


def test_line_spacing_falls_back_to_single() -> None:
    assert fmt_line_spacing(100, 12) == ('Single', '20')
    assert fmt_line_spacing(None, 12) == ('Single', '20')
    assert fmt_line_spacing(125, None) == ('Single', '20')     # Größe unbekannt
    assert fmt_line_spacing('kaputt', 12) == ('Single', '20')
    assert fmt_line_spacing(9999, 12) == ('Single', '20')       # unplausibel


def test_line_spacing_uses_largest_font_of_block() -> None:
    """Ein Block mit gemischten Größen bekommt die Zeilenhöhe der GRÖSSTEN."""
    style = dict(fam='Arial', color='#000000', bold=False, ital=False, under=False)
    blocks = [[('klein', dict(style, size=10)), ('GROSS', dict(style, size=20))]]
    doc = fmt_document(blocks, 'left', line_height=125)
    assert 'LineSpacingRule="Exactly" LineSpacing="25"' in doc


def test_fmt_size_normalises() -> None:
    assert fmt_size(13.0) == '13'
    assert fmt_size(13.5) == '13.5'
    assert fmt_size('18px') == '18'
    assert fmt_size('kaputt') == '18'
    assert fmt_size(0) == '18'
