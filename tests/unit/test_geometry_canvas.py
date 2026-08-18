#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geometry (Canvas-abhängige Rect- und Schriftumrechnung) + Canvas-Erkennung."""
from __future__ import annotations

import io
import zipfile

import pytest

from ats2story.ats_reader.canvas import DEFAULT_CANVAS, detect_canvas
from ats2story.geometry import PX_TO_PT, Geometry, fill_rect, fit_rect, native_rect

NS = 'http://im-c.de/xml/authoring/1.0'


def _ata(rects: list[tuple], thumb: tuple[int, int] | None) -> bytes:
    """Minimale .ata-ZIP mit document.xml (rects) und optionalem Thumbnail."""
    from PIL import Image

    body = ''.join(
        f'<image layer="{i}"><complexproperty name="rect">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/></complexproperty></image>'
        for i, (x, y, w, h) in enumerate(rects))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('document/document.xml',
                   f'<?xml version="1.0"?><document xmlns="{NS}">{body}</document>')
        if thumb is not None:
            png = io.BytesIO()
            Image.new('RGB', thumb, 'white').save(png, 'PNG')
            z.writestr('meta/thumbnail.png', png.getvalue())
    return buf.getvalue()


def _scenes(atas: list[bytes]) -> list[dict]:
    return [dict(name='S', slides=[dict(name=f'F{i}', ata=b) for i, b in enumerate(atas)])]


# ---- Geometry --------------------------------------------------------------

def test_geometry_matches_module_functions_on_default_canvas() -> None:
    """Mit dem Default-Canvas rechnet Geometry exakt wie die Modul-Funktionen."""
    probe = (12.0, 34.0, 200.0, 90.0)
    assert Geometry('fit')(*probe) == pytest.approx(fit_rect(*probe))
    assert Geometry('fill')(*probe) == pytest.approx(fill_rect(*probe))
    assert Geometry('native')(*probe) == pytest.approx(native_rect(*probe))


def test_geometry_fit_keeps_whole_canvas_visible() -> None:
    """'fit' passt den KOMPLETTEN Canvas in die Bühne (kein Überstand)."""
    for canvas in ((1024, 748), (950, 630)):
        g = Geometry('fit', *canvas)
        L, T, R, B = g(0, 0, *canvas)
        assert L >= -0.001 and T >= -0.001
        assert R <= g.story_w + 0.001 and B <= g.story_h + 0.001


def test_geometry_fill_covers_stage_and_may_overflow() -> None:
    g = Geometry('fill', 1024, 748)
    L, T, R, B = g(0, 0, 1024, 748)
    assert (R - L) >= g.story_w - 0.001          # Bühne voll bedeckt
    assert T < 0 and B > g.story_h               # Überstand oben/unten


def test_geometry_native_uses_detected_canvas_as_story_size() -> None:
    g = Geometry('native', 950, 630)
    assert (g.story_w, g.story_h) == (950, 630)
    assert g(10, 20, 30, 40) == (10, 20, 40, 60)
    assert g.scale == 1.0


def test_font_pt_converts_px_and_scale() -> None:
    """imc-px -> Storyline-pt: Wert * Canvas-Faktor * 0,75."""
    g = Geometry('fit', 1024, 748)
    assert g.font_pt(18) == pytest.approx(round(18 * g.scale * PX_TO_PT, 1))
    assert g.font_pt(18) < 18                     # der eigentliche Fehler von früher
    assert Geometry('native', 1024, 748).font_pt(18) == pytest.approx(13.5)


def test_font_pt_is_robust_against_junk() -> None:
    g = Geometry('native')
    assert g.font_pt('21px') == pytest.approx(15.8, abs=0.1)
    assert g.font_pt(None) == g.font_pt(18)
    assert g.font_pt('') == g.font_pt(18)
    assert g.font_pt(0) == g.font_pt(18)
    assert g.font_pt(100000) <= 200.0             # gedeckelt


# ---- Canvas-Erkennung ------------------------------------------------------

def test_detect_canvas_prefers_thumbnail_size() -> None:
    scenes = _scenes([_ata([(0, 0, 100, 100)], thumb=(950, 630))] * 3)
    assert detect_canvas(scenes) == (950, 630)


def test_detect_canvas_majority_wins() -> None:
    atas = [_ata([(0, 0, 10, 10)], thumb=(1024, 748)) for _ in range(3)]
    atas.append(_ata([(0, 0, 10, 10)], thumb=(640, 480)))
    assert detect_canvas(_scenes(atas)) == (1024, 748)


def test_detect_canvas_falls_back_to_rect_extent() -> None:
    """Ohne Thumbnail entscheidet die Ausdehnung, gerundet auf ein Profil."""
    scenes = _scenes([_ata([(0, 0, 940, 620), (10, 10, 100, 20)], thumb=None)])
    assert detect_canvas(scenes) == (950, 630)


def test_detect_canvas_default_without_any_signal() -> None:
    assert detect_canvas([]) == DEFAULT_CANVAS
    assert detect_canvas(_scenes([b'kein zip'])) == DEFAULT_CANVAS
