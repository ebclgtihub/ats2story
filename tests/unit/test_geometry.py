#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für ats2story.geometry."""
from __future__ import annotations

import pytest

from ats2story.geometry import (
    ATS_H,
    ATS_W,
    NATIVE_H,
    NATIVE_W,
    SLD_H,
    SLD_W,
    extract_element,
    fill_rect,
    find_first,
    fit_rect,
    native_rect,
)


def test_fit_rect_full_canvas_reference() -> None:
    """Referenzwert (bit-identisch zum Monolith): fit_rect(0,0,1024,748).

    Hinweis: Der exakte Wert des Original-Codes ist 147.16577…/1132.83422…
    (scale = 720/748). Diese Invariante darf sich beim Refactor NICHT ändern.
    """
    l, t, r, b = fit_rect(0, 0, ATS_W, ATS_H)
    assert l == pytest.approx(147.16577540, abs=1e-6)
    assert t == pytest.approx(0.0, abs=1e-6)
    assert r == pytest.approx(1132.83422459, abs=1e-6)
    assert b == pytest.approx(720.0, abs=1e-6)


def test_fit_rect_is_letterboxed_within_slide() -> None:
    l, t, r, b = fit_rect(0, 0, ATS_W, ATS_H)
    # Vollständig sichtbar: linke/rechte Balken, oben/unten bündig.
    assert l > 0 and r < SLD_W
    assert t == pytest.approx(0.0)
    assert b == pytest.approx(SLD_H)


def test_fill_rect_covers_full_width_no_side_bars() -> None:
    l, t, r, b = fill_rect(0, 0, ATS_W, ATS_H)
    # Breite voll abgedeckt (keine Seitenbalken).
    assert l == pytest.approx(0.0, abs=1e-6)
    assert r == pytest.approx(SLD_W, abs=1e-6)
    # Höhe ragt über den Rand (Crop oben/unten).
    assert t < 0 and b > SLD_H


def test_fill_rect_scale_larger_than_fit() -> None:
    # Ein 100x100-Rect ist unter fill breiter als unter fit (max vs min scale).
    fl, ft, fr, fb = fit_rect(0, 0, 100, 100)
    xl, xt, xr, xb = fill_rect(0, 0, 100, 100)
    assert (xr - xl) > (fr - fl)


def test_native_rect_is_identity() -> None:
    """native: rohe imc-Koordinaten 1:1 als (l,t,r,b) — keine Skalierung."""
    assert native_rect(0, 0, ATS_W, ATS_H) == (0, 0, ATS_W, ATS_H)
    assert native_rect(10, 20, 100, 50) == (10, 20, 110, 70)


def test_native_canvas_matches_ats_canvas() -> None:
    assert (NATIVE_W, NATIVE_H) == (ATS_W, ATS_H) == (1024, 748)


def test_extract_element_balances_nested_same_name() -> None:
    s = '<pre><pic a="1"><pic b="2"/></pic></pre>'
    start = s.find('<pic')
    frag = extract_element(s, start, 'pic')
    assert frag == '<pic a="1"><pic b="2"/></pic>'


def test_extract_element_prefix_collision() -> None:
    # <picFormat> darf <pic …>…</pic> nicht stören.
    s = '<wrap><picFormat x="1" /><pic id="3"><inner/></pic></wrap>'
    start = s.find('<pic ')
    frag = extract_element(s, start, 'pic')
    assert frag == '<pic id="3"><inner/></pic>'


def test_find_first_skips_prefix_collisions() -> None:
    s = '<picFormat/><pic id="5"/>'
    i = find_first(s, '<pic')
    assert s[i:i + 4] == '<pic'
    assert s[i + 4] == ' '  # echtes <pic , nicht <picFormat


def test_find_first_returns_minus_one_when_absent() -> None:
    assert find_first('<other/>', '<pic') == -1
