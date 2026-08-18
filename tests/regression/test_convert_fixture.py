#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressionstest: echte .ats -> .story Konvertierung + Konsistenz-Validator.

Deckt den End-to-End-Pfad (CLI/converter/story_writer/opc_writer) gegen die
echte lokale .ats-Fixture ab (s. tests/conftest.py). validate_story.main() muss 0 (= keine
Fehler) liefern.
"""
from __future__ import annotations

import importlib.util
import os
import zipfile

import ats2story


def _load_validate_story(project_root: str):
    """validate_story.py als Modul laden (liegt im Projekt-Root, kein Paket)."""
    path = os.path.join(project_root, 'validate_story.py')
    spec = importlib.util.spec_from_file_location('validate_story', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_convert_mini_no_audio_validates_clean(tmp_path, fixture_ats, fixture_tpl, project_root) -> None:
    out = str(tmp_path / 'reg_mini.story')
    stats = ats2story.convert_ats(
        fixture_ats, out, tpl=fixture_tpl, max_slides=5, no_audio=True,
        progress=lambda f, m: None)

    assert stats['slides'] == 5
    assert stats['bad'] is None          # testzip() ok
    assert stats['media'] > 0
    assert os.path.isfile(out)

    validate_story = _load_validate_story(project_root)
    rc = validate_story.main(out)
    assert rc == 0, 'validate_story meldete Fehler im erzeugten .story'


def test_convert_single_scene_structure(tmp_path, fixture_ats, fixture_tpl, project_root) -> None:
    out = str(tmp_path / 'reg_single.story')
    stats = ats2story.convert_ats(
        fixture_ats, out, tpl=fixture_tpl, max_slides=4, no_audio=True,
        single_scene=True, scene_name='Kurs', progress=lambda f, m: None)
    assert stats['scenes'] == 1
    validate_story = _load_validate_story(project_root)
    assert validate_story.main(out) == 0


def test_convert_geometry_fill_validates_clean(tmp_path, fixture_ats, fixture_tpl, project_root) -> None:
    """geometry='fill' darf das Paket nicht korrumpieren (Validator = 0 Fehler)."""
    out = str(tmp_path / 'reg_fill.story')
    stats = ats2story.convert_ats(
        fixture_ats, out, tpl=fixture_tpl, max_slides=4, no_audio=True,
        geometry='fill', progress=lambda f, m: None)
    assert stats['bad'] is None
    validate_story = _load_validate_story(project_root)
    assert validate_story.main(out) == 0


def test_convert_geometry_native_validates_and_resizes(tmp_path, fixture_ats, fixture_tpl,
                                                       project_root) -> None:
    """geometry='native': Validator = 0 Fehler UND Story-Size = ERKANNTER
    imc-Canvas der Fixture (950x630, NICHT die alten festen 1024x748) —
    prop id=15 in story.xml sowie sldSz in den Folien-Shapes."""
    out = str(tmp_path / 'reg_native.story')
    stats = ats2story.convert_ats(
        fixture_ats, out, tpl=fixture_tpl, max_slides=3, no_audio=True,
        geometry='native', progress=lambda f, m: None)
    assert stats['slides'] == 3
    assert stats['bad'] is None
    validate_story = _load_validate_story(project_root)
    assert validate_story.main(out) == 0

    with zipfile.ZipFile(out) as z:
        story = z.read('story/story.xml').decode('utf-8')
        assert '<prop id="15"><sz w="950" h="630" /></prop>' in story
        slide = z.read('story/slides/slide.xml').decode('utf-8')
        assert '<sldSz w="950" h="630" />' in slide
        assert '<sldSz w="1280"' not in slide


def test_stats_dict_has_app_keys(tmp_path, fixture_ats, fixture_tpl) -> None:
    """app.py liest diese Keys — sie müssen vorhanden bleiben."""
    out = str(tmp_path / 'reg_keys.story')
    stats = ats2story.convert_ats(
        fixture_ats, out, tpl=fixture_tpl, max_slides=2, no_audio=True,
        progress=lambda f, m: None)
    for key in ('slides', 'scenes', 'media', 'size', 'ocr_replaced', 'ocr_conf',
                'bad', 'skipped_imgs', 'skipped_slides', 'skipped_audio',
                'ocr_errors', 'skipped_detail'):
        assert key in stats


def test_story_package_is_valid_zip(tmp_path, fixture_ats, fixture_tpl) -> None:
    out = str(tmp_path / 'reg_zip.story')
    ats2story.convert_ats(fixture_ats, out, tpl=fixture_tpl, max_slides=2,
                          no_audio=True, progress=lambda f, m: None)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        names = set(z.namelist())
        assert 'story/story.xml' in names
        assert '[Content_Types].xml' in names
