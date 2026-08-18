#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für set_story_size (geometry='native' — Story-Size umstellen)."""
from __future__ import annotations

from ats2story.story_writer import set_story_size


class _FakeTpl:
    """Minimales Template-Double mit den von set_story_size gepatchten Attributen."""

    def __init__(self) -> None:
        self.story = (
            '<story><propLst><prop id="15"><sz w="1280" h="720" /></prop>'
            '<prop id="18">Autor</prop></propLst></story>')
        self.pic_stencil = (
            '<pic assetG="x"><sldSz w="1280" h="720" /><loc l="0" t="0" r="1" b="1" />'
            '<propBag><prop><key>oldsize</key><val><sz w="1280" h="720" /></val></prop>'
            '<prop><key>oldDesignedSlideSizeProp</key><val><sz w="1280" h="720" /></val></prop>'
            '</propBag></pic>')
        self.tb_stencil = (
            '<textBox><sldSz w="1280" h="720" /><loc l="0" t="0" r="1" b="1" />'
            '<propBag><prop><key>oldsize</key><val><sz w="1280" h="720" /></val></prop>'
            '</propBag></textBox>')
        self.snd_stencil = '<sound><sldSz w="1280" h="720" /><loc l="0" t="0" r="1" b="1" /></sound>'
        self.slide_skeleton = (
            '<sld><sldSz w="1280" h="720" /><shapeLst>{SHAPES}</shapeLst>'
            '<propBag><prop><key>oldsize</key><val><sz w="1280" h="720" /></val></prop>'
            '<prop><key>oldprojguid</key><val g="0" /></prop></propBag></sld>')


def test_set_story_size_patches_prop15() -> None:
    tpl = _FakeTpl()
    set_story_size(tpl, 1024, 748)
    assert '<prop id="15"><sz w="1024" h="748" /></prop>' in tpl.story
    assert 'w="1280"' not in tpl.story


def test_set_story_size_patches_all_sldsz_in_stencils_and_skeleton() -> None:
    tpl = _FakeTpl()
    set_story_size(tpl, 1024, 748)
    for frag in (tpl.pic_stencil, tpl.tb_stencil, tpl.snd_stencil, tpl.slide_skeleton):
        assert '<sldSz w="1024" h="748" />' in frag
        assert '<sldSz w="1280"' not in frag


def test_set_story_size_patches_oldsize_propbag() -> None:
    tpl = _FakeTpl()
    set_story_size(tpl, 1024, 748)
    assert 'oldsize</key><val><sz w="1024" h="748" />' in tpl.pic_stencil
    assert 'oldDesignedSlideSizeProp</key><val><sz w="1024" h="748" />' in tpl.pic_stencil
    assert 'oldsize</key><val><sz w="1024" h="748" />' in tpl.slide_skeleton


def test_set_story_size_leaves_locs_and_other_props_alone() -> None:
    tpl = _FakeTpl()
    set_story_size(tpl, 1024, 748)
    assert '<loc l="0" t="0" r="1" b="1" />' in tpl.pic_stencil
    assert '<prop id="18">Autor</prop>' in tpl.story
    assert 'oldprojguid</key><val g="0" />' in tpl.slide_skeleton


def test_set_story_size_tolerates_missing_stencils() -> None:
    tpl = _FakeTpl()
    tpl.snd_stencil = None
    set_story_size(tpl, 1024, 748)
    assert tpl.snd_stencil is None
    assert '<sldSz w="1024" h="748" />' in tpl.pic_stencil
