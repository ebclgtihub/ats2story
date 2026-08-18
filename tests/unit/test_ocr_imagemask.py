#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grafikerhalt bei OCR (imagemask) + Farbbestimmung je Textbereich.

Rein synthetisch, ohne Tesseract: die Funktionen bekommen die Textkästen
direkt übergeben.
"""
from __future__ import annotations

import io

import pytest

from PIL import Image, ImageDraw

from ats2story.ocr.engine import _region_color
from ats2story.ocr.imagemask import erase_text_regions, nontext_ink_ratio


def _img(draw_fn, size=(400, 300), bg='white'):
    im = Image.new('RGB', size, bg)
    draw_fn(ImageDraw.Draw(im))
    return im


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def test_nontext_ratio_zero_for_pure_text_image() -> None:
    """Alle Tinte liegt in den Kästen -> Bild ist reiner Text (wird ersetzt)."""
    im = _img(lambda d: d.rectangle((50, 50, 250, 90), fill='black'))
    ratio = nontext_ink_ratio(im.convert('L'), [(45, 45, 255, 95)])
    assert ratio == pytest.approx(0.0, abs=0.01)


def test_nontext_ratio_high_when_graphic_next_to_text() -> None:
    """Diagramm neben der Beschriftung -> Bild bleibt erhalten."""
    def draw(d):
        d.rectangle((20, 20, 200, 200), fill='#3366CC')     # Grafik
        d.rectangle((240, 250, 380, 280), fill='black')     # „Text"
    ratio = nontext_ink_ratio(_img(draw).convert('L'), [(235, 245, 385, 285)])
    assert ratio > 0.5


def test_erase_text_regions_clears_box_and_keeps_graphic() -> None:
    def draw(d):
        d.rectangle((20, 20, 200, 200), fill='#3366CC')
        d.rectangle((240, 250, 380, 280), fill='black')
    src = _img(draw)
    out = erase_text_regions(_png(src), [(240, 250, 380, 280)])
    assert out is not None
    res = Image.open(io.BytesIO(out)).convert('RGB')
    assert res.getpixel((310, 265))[0] > 200          # Textstelle ist Hintergrund
    assert res.getpixel((100, 100))[2] > 150          # Grafik unangetastet (blau)


def test_erase_text_regions_scales_ocr_coordinates() -> None:
    """OCR arbeitet ggf. auf einem 2x-Upscale — die Kästen müssen zurückgerechnet
    werden, sonst wird die falsche Bildstelle gestempelt."""
    src = _img(lambda d: d.rectangle((50, 50, 150, 100), fill='black'))
    out = erase_text_regions(_png(src), [(100, 100, 300, 200)], scale=2.0)
    res = Image.open(io.BytesIO(out)).convert('RGB')
    assert res.getpixel((100, 75))[0] > 200           # Original-Koordinaten geleert


def test_erase_text_regions_without_boxes_returns_none() -> None:
    src = _img(lambda d: d.rectangle((10, 10, 20, 20), fill='black'))
    assert erase_text_regions(_png(src), []) is None
    assert erase_text_regions(b'kein bild', [(0, 0, 5, 5)]) is None


def _strokes(fg):
    """Schriftzug-Attrappe: dünne Striche, die (wie echte Glyphen) nur einen
    kleinen Teil des Kastens bedecken."""
    def draw(d):
        for y in range(40, 90, 10):
            d.rectangle((40, y, 360, y + 2), fill=fg)
        for x in range(40, 360, 40):
            d.rectangle((x, 40, x + 2, 90), fill=fg)
    return draw


@pytest.mark.parametrize('bg,fg', [('white', (0, 51, 102)),
                                   ('#102040', (255, 255, 255)),
                                   ('#EEEEEE', (176, 0, 0))])
def test_region_color_finds_ink_on_light_and_dark(bg, fg) -> None:
    """Auch HELLE Schrift auf dunklem Grund — früher kam immer #222222."""
    im = _img(_strokes(fg), bg=bg)
    got = _region_color(im.convert('RGBA'), (30, 30, 370, 100))
    assert got == '#{:02X}{:02X}{:02X}'.format(*fg)


def test_region_color_none_without_contrast() -> None:
    im = _img(lambda d: None, bg='white')
    assert _region_color(im.convert('RGBA'), (10, 10, 200, 100)) is None
    assert _region_color(im.convert('RGBA'), None) is None
