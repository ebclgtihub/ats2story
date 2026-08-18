#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shape-Attribute: Rotation, Füllung/Rahmen, Bild-Deckkraft.

Diese Pfade kommen in den vorliegenden Beispielkursen NICHT vor (dort ist
durchgehend ``rotation="0"``, ``opacity="100"``, ``fill/stroke style="0"``).
Genau deshalb brauchen sie Tests, die sie erzwingen — sonst wären sie
ungeprüfter Code. Das Schema stammt aus echten Storyline-Dateien:
``rot="-1"`` = keine Rotation, ``<solidFill><clr><srgbClr val="…"/></clr>``.
"""
from __future__ import annotations

import io

from PIL import Image

from ats2story.media import apply_opacity
from ats2story.story_writer.shapes import _apply_bg, _clr, _rot_attr


def test_rot_attr_uses_storyline_sentinel() -> None:
    assert _rot_attr(0) == '-1'          # Storyline: -1 = keine Rotation
    assert _rot_attr(None) == '-1'
    assert _rot_attr(360) == '-1'
    assert _rot_attr(90) == '90'
    assert _rot_attr(-90) == '270'
    assert _rot_attr(15.4) == '15'
    assert _rot_attr('kaputt') == '-1'


def test_clr_fragment_with_and_without_alpha() -> None:
    assert _clr('#1B6853') == '<clr><srgbClr val="1B6853" /></clr>'
    assert _clr('1b6853', 50) == '<clr><srgbClr val="1B6853" /><alpha val="50000" /></clr>'


def _stencil() -> str:
    return ('<textBox rot="-1" autoFit="resize"><bG shine="false"><noFill /><noLine />'
            '<lineStyle w="3" scale="1" /></bG></textBox>')


def test_apply_bg_replaces_nofill_and_noline() -> None:
    out = _apply_bg(_stencil(), '#CC0000', ('#003366', 3))
    assert '<solidFill><clr><srgbClr val="CC0000" /></clr></solidFill>' in out
    assert '<solidLine><clr><srgbClr val="003366" /></clr></solidLine>' in out
    assert '<lineStyle w="3"' in out
    assert '<noFill />' not in out and '<noLine />' not in out


def test_apply_bg_without_values_changes_nothing() -> None:
    """imc liefert in beiden Beispielkursen durchgehend style="0" — dann muss
    das Fragment BYTEGLEICH bleiben."""
    assert _apply_bg(_stencil(), None, None) == _stencil()


def test_apply_bg_sets_line_width() -> None:
    out = _apply_bg(_stencil(), None, ('#000000', 7))
    assert '<lineStyle w="7"' in out


def _png(color=(0, 0, 255, 255), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGBA', size, color).save(buf, 'PNG')
    return buf.getvalue()


def test_apply_opacity_scales_alpha_channel() -> None:
    out = apply_opacity(_png(), 40)
    assert Image.open(io.BytesIO(out)).convert('RGBA').getpixel((0, 0))[3] == 102


def test_apply_opacity_is_identity_at_full_opacity() -> None:
    raw = _png()
    assert apply_opacity(raw, 100) is raw
    assert apply_opacity(raw, None) is raw


def test_apply_opacity_survives_broken_input() -> None:
    assert apply_opacity(b'kein bild', 50) == b'kein bild'
