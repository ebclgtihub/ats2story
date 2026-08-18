#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für das richtext-Paket."""
from __future__ import annotations

from ats2story.richtext import fmt_document, inline_runs, norm_color, parse_richtext


class FakeElem:
    """Minimaler Element-Stub mit .get (wie ElementTree-Element)."""

    def __init__(self, **attrs):
        self._a = attrs

    def get(self, k, default=None):
        return self._a.get(k, default)


def test_norm_color_hash_and_short() -> None:
    assert norm_color('#abc') == '#AABBCC'
    assert norm_color('ff0000') == '#FF0000'
    assert norm_color(None) == '#000000'
    assert norm_color('garbage') == '#000000'


def test_parse_richtext_splits_paragraphs() -> None:
    el = FakeElem(fontFamily='Arial', fontSize='18', textColor='#000000')
    blocks = parse_richtext('<p>Erster</p><p>Zweiter</p>', el)
    texts = [''.join(t for t, _ in b).strip() for b in blocks]
    assert 'Erster' in texts
    assert 'Zweiter' in texts


def test_parse_richtext_inherits_element_style() -> None:
    el = FakeElem(fontFamily='Times', fontSize='24', textColor='#FF0000',
                  fontBold='true')
    blocks = parse_richtext('<p>Hallo</p>', el)
    _text, style = blocks[0][0]
    assert style['fam'] == 'Times'
    assert style['size'] == '24'
    assert style['bold'] is True


def test_inline_runs_bold_italic() -> None:
    base = dict(fam='Arial', size='18', color='#000000',
                bold=False, ital=False, under=False)
    runs = inline_runs('normal <b>fett</b> <i>kursiv</i>', base)
    flat = {txt.strip(): st for txt, st in runs if txt.strip()}
    assert flat['fett']['bold'] is True
    assert flat['kursiv']['ital'] is True


def test_inline_runs_span_color_and_size() -> None:
    base = dict(fam='Arial', size='18', color='#000000',
                bold=False, ital=False, under=False)
    runs = inline_runs('<span style="color:#00FF00;font-size:30">grün</span>', base)
    txt, st = runs[0]
    assert st['color'].lower() == '#00ff00'
    assert st['size'] == '30'


def test_fmt_document_roundtrip_contains_text() -> None:
    blocks = [[('Hallo Welt', dict(fam='Arial', size='18', color='#112233',
                                    bold=True, ital=False, under=False))]]
    doc = fmt_document(blocks, 'center')
    # doppelt-escaped: < -> &lt; ; Text bleibt enthalten
    assert 'Hallo Welt' in doc
    assert '&lt;Document' in doc
    assert 'Center' in doc           # Ausrichtung
    # Doppel-Quotes in Attributen bleiben unescaped (nur &,<,> werden ersetzt)
    assert 'FontIsBold="True"' in doc


def test_fmt_document_escapes_ampersand() -> None:
    blocks = [[('A & B', dict(fam='Arial', size='18', color='#000000',
                              bold=False, ital=False, under=False))]]
    doc = fmt_document(blocks)
    # & wird zu &amp; (durch html.escape) und dann nochmal escaped
    assert '&amp;amp;' in doc
