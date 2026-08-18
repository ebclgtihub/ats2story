#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integrationstests für Template/Builder/clean_backgrounds gegen echte Vorlage."""
from __future__ import annotations

import pytest

from ats2story.media import MediaPool
from ats2story.story_writer import Builder, Template, clean_backgrounds


def test_template_extracts_stencils(fixture_tpl: str) -> None:
    tpl = Template(fixture_tpl)
    assert tpl.pic_stencil and '<pic' in tpl.pic_stencil
    assert tpl.tb_stencil and '<textBox' in tpl.tb_stencil
    assert tpl.snd_stencil and '<sound' in tpl.snd_stencil
    assert '{SHAPES}' in tpl.slide_skeleton
    assert tpl.preserve                       # GUIDs aus Masters/Layouts
    assert isinstance(tpl.keep_md5, set)


def test_clean_backgrounds_replaces_and_tracks_md5(fixture_tpl: str) -> None:
    tpl = Template(fixture_tpl)
    story_before = tpl.story
    n = clean_backgrounds(tpl)
    # Die echte Budget-Vorlage bringt Hintergrund-Bilder UND dekorative
    # Farbflächen (Footer-Leiste etc.) mit — es MUSS also mind. ein Element
    # gesäubert werden. (Ersetzt das frühere tautologische ``assert n >= 0``.)
    assert n > 0, 'clean_backgrounds säuberte kein einziges Element'
    # story.xml md5-Verweise wurden mitgezogen (Inhalt änderte sich).
    assert tpl.story != story_before


def test_builder_exam_slide_is_wellformed(fixture_tpl: str) -> None:
    import xml.etree.ElementTree as ET

    tpl = Template(fixture_tpl)
    builder = Builder(tpl, MediaPool())
    sld, rels, guid, dur, used = builder.build_slide(
        dict(exam=True, name='Quiz X'), 'slide.xml', 1)
    ET.fromstring(sld.encode('utf-8'))        # wohlgeformt
    ET.fromstring(rels.encode('utf-8'))
    assert len(guid) == 36
    assert used == []
    assert dur > 0


def test_builder_exam_textbox_is_visible(fixture_tpl: str) -> None:
    """Regression (H-2): Exam-Platzhalter-Textbox muss ein sichtbares
    Rechteck haben (B > T und R > L), nicht das alte umgedrehte (160,300,960,140)."""
    import re

    tpl = Template(fixture_tpl)
    builder = Builder(tpl, MediaPool())
    sld, _rels, _guid, _dur, _used = builder.build_slide(
        dict(exam=True, name='Quiz X'), 'slide.xml', 1)
    m = re.search(r'<loc l="([\d.-]+)" t="([\d.-]+)" r="([\d.-]+)" b="([\d.-]+)"', sld)
    assert m is not None, 'Exam-Folie hat keine <loc>-Textbox'
    L, T, R, B = (float(x) for x in m.groups())
    assert R > L, f'Breite nicht positiv: L={L} R={R}'
    assert B > T, f'Höhe nicht positiv (unsichtbar!): T={T} B={B}'


def test_builder_geometry_fill_uses_fill_transform(fixture_tpl: str) -> None:
    """Modus-String -> Geometry mit Default-Canvas, rechnerisch wie die
    Modul-Funktionen fit_rect/fill_rect (Identität gilt seit der
    Canvas-Erkennung nicht mehr, das Ergebnis muss aber gleich bleiben)."""
    from ats2story.geometry import fill_rect, fit_rect

    tpl = Template(fixture_tpl)
    b_fit = Builder(tpl, MediaPool(), geometry='fit')
    b_fill = Builder(tpl, MediaPool(), geometry='fill')
    probe = (10.0, 20.0, 300.0, 100.0)
    assert b_fit.rect_transform(*probe) == pytest.approx(fit_rect(*probe))
    assert b_fill.rect_transform(*probe) == pytest.approx(fill_rect(*probe))
    assert b_fit.rect_transform(*probe) != pytest.approx(b_fill.rect_transform(*probe))


def test_builder_geometry_accepts_detected_canvas(fixture_tpl: str) -> None:
    """Eine kalibrierte Geometry (abweichender Canvas) wird durchgereicht und
    liefert andere Koordinaten als der 1024x748-Default."""
    from ats2story.geometry import Geometry, fit_rect

    tpl = Template(fixture_tpl)
    b = Builder(tpl, MediaPool(), geometry=Geometry('fit', 950, 630))
    probe = (0.0, 0.0, 950.0, 630.0)
    L, T, R, B = b.rect_transform(*probe)
    # 950x630 ist höher als 16:9 -> 'fit' ist HÖHEN-getrieben: volle 720 px
    # Höhe, links/rechts Balken; der Canvas bleibt vollständig sichtbar.
    assert (B - T) == pytest.approx(720.0)
    assert (R - L) == pytest.approx(950 * 720 / 630)
    assert L == pytest.approx((1280 - (R - L)) / 2)
    assert b.rect_transform(*probe) != pytest.approx(fit_rect(*probe))
