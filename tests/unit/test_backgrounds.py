#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDD-Spec für ats2story.story_writer.backgrounds._whiten_solid_fills.

Kodiert die VOLLE Soll-Behandlung von ``<solidFill>``-Farben. Einige Fälle
schlagen gegen den aktuellen (noch un-gefixten) Code absichtlich FEHL — sie
sind die Spezifikation, die der Hintergrund-Fix grün machen soll:

  * plain self-closing ``srgbClr``            -> weiß              (heute grün)
  * self-closing ``schemeClr``                -> weiß              (heute grün)
  * genestetes ``<alpha>`` bleibt erhalten    -> Farbe weiß, alpha (heute ROT)
  * genestetes ``<shade>`` / ``<tint>``       -> MUSS geweißt sein (heute ROT)
  * ``<gradFill>`` bleibt unberührt           -> nur solidFill weiß (heute grün)

Alle Farb-Asserts sind case-insensitiv (``FFFFFF``), damit der Fix die exakte
Groß-/Kleinschreibung frei wählen kann.
"""
from __future__ import annotations

import re

import pytest

from ats2story.story_writer.backgrounds import _whiten_solid_fills

_WHITE = re.compile(r'val="ffffff"', re.I)
_NON_WHITE_COLOR = re.compile(r'<(?:srgbClr|schemeClr)\b[^>]*val="(?!ffffff")', re.I)


def _colors(xml: str) -> list[str]:
    """Alle Farb-Werte (val=...) innerhalb von Farb-Tags, klein geschrieben."""
    return [v.lower() for v in re.findall(
        r'<(?:srgbClr|schemeClr)\b[^>]*?val="([0-9A-Fa-f]{6}|\w+)"', xml)]


# ---------------------------------------------------------------------------
# Fälle, die BEREITS grün sind (Absicherung, kein Regress).
# ---------------------------------------------------------------------------

def test_plain_srgb_clr_becomes_white() -> None:
    xml = '<solidFill><srgbClr val="FF0000"/></solidFill>'
    out, n = _whiten_solid_fills(xml)
    assert n == 1
    assert _WHITE.search(out), out
    assert not _NON_WHITE_COLOR.search(out), f'Restfarbe geblieben: {out}'


def test_scheme_clr_becomes_white() -> None:
    xml = '<solidFill><schemeClr val="accent1"/></solidFill>'
    out, n = _whiten_solid_fills(xml)
    assert n == 1
    assert _WHITE.search(out), out
    # schemeClr muss durch weiße Farbe ersetzt sein — kein Rest-Schema-Verweis.
    assert 'accent1' not in out, out


def test_returns_input_unchanged_when_no_solid_fill() -> None:
    xml = '<p><r>kein fill hier</r></p>'
    out, n = _whiten_solid_fills(xml)
    assert n == 0
    assert out == xml


# ---------------------------------------------------------------------------
# TDD-Spec: heute ROT — der Hintergrund-Fix macht sie grün.
# ---------------------------------------------------------------------------

def test_nested_alpha_is_preserved_while_color_whitened() -> None:
    """Farbe -> weiß, aber ``<alpha>`` (Transparenz) bleibt erhalten.

    Heute ROT: der Regex matcht nur self-closing Farb-Tags, verfehlt also
    ``<srgbClr ...><alpha/></srgbClr>`` komplett (n==0).
    """
    xml = '<solidFill><srgbClr val="FF0000"><alpha val="50000"/></srgbClr></solidFill>'
    out, n = _whiten_solid_fills(xml)
    assert n == 1, f'Nested-alpha-solidFill nicht behandelt: {out}'
    assert _WHITE.search(out), f'Farbe nicht geweißt: {out}'
    assert '<alpha val="50000"/>' in out, f'alpha nicht erhalten: {out}'
    assert not _NON_WHITE_COLOR.search(out), f'Restfarbe geblieben: {out}'


def test_nested_shade_is_whitened_and_modifier_removed() -> None:
    """``<shade>`` verdunkelt die Farbe — auf Weiß ist das sinnlos und würde
    Grau ergeben. Der Fill MUSS reinweiß rendern, also: Farbe weiß UND
    ``<shade>`` entfernt. Heute ROT (n==0, shade überlebt)."""
    xml = '<solidFill><srgbClr val="00B050"><shade val="50000"/></srgbClr></solidFill>'
    out, n = _whiten_solid_fills(xml)
    assert n == 1, f'shade-solidFill nicht behandelt: {out}'
    assert _WHITE.search(out), f'Farbe nicht geweißt: {out}'
    assert 'shade' not in out, f'shade nicht entfernt (Fill nicht reinweiß): {out}'
    assert not _NON_WHITE_COLOR.search(out), out


def test_nested_tint_is_whitened_and_modifier_removed() -> None:
    """``<tint>`` analog zu shade: auf Weiß sinnlos, MUSS entfernt werden.
    Heute ROT."""
    xml = '<solidFill><schemeClr val="accent1"><tint val="60000"/></schemeClr></solidFill>'
    out, n = _whiten_solid_fills(xml)
    assert n == 1, f'tint-solidFill nicht behandelt: {out}'
    assert _WHITE.search(out), f'Farbe nicht geweißt: {out}'
    assert 'tint' not in out, f'tint nicht entfernt (Fill nicht reinweiß): {out}'
    assert 'accent1' not in out, out


# ---------------------------------------------------------------------------
# gradFill: NUR solidFill wird geweißt, Gradienten bleiben unberührt.
# ---------------------------------------------------------------------------

def test_grad_fill_is_left_untouched() -> None:
    """``<gradFill>`` ist kein ``<solidFill>`` -> unverändert, n zählt ihn nicht."""
    xml = (
        '<gradFill><gsLst>'
        '<gs pos="0"><srgbClr val="FF0000"/></gs>'
        '<gs pos="100000"><srgbClr val="0000FF"/></gs>'
        '</gsLst></gradFill>'
    )
    out, n = _whiten_solid_fills(xml)
    assert n == 0, f'gradFill fälschlich behandelt: {out}'
    assert out == xml, 'gradFill wurde verändert'


def test_solid_fill_whitened_next_to_grad_fill() -> None:
    """Gemischt: der solidFill wird weiß, der benachbarte gradFill bleibt."""
    xml = (
        '<solidFill><srgbClr val="00B050"/></solidFill>'
        '<gradFill><gsLst><gs pos="0"><srgbClr val="FF0000"/></gs></gsLst></gradFill>'
    )
    out, n = _whiten_solid_fills(xml)
    assert n == 1, out
    assert '<gradFill>' in out and 'val="FF0000"' in out, 'gradFill-Farbe verändert'
    # Genau die solidFill-Farbe (00B050) muss verschwunden/weiß sein.
    assert '00B050' not in out, out
    assert _WHITE.search(out), out
