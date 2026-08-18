#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integrationstests für ats_reader gegen die echte Regression-Fixture."""
from __future__ import annotations

import zipfile

from ats2story.ats_reader import slide_content, thumbnail, walk_course


def test_walk_course_finds_scenes_and_slides(fixture_ats: str) -> None:
    with zipfile.ZipFile(fixture_ats) as z:
        scenes = walk_course(z)
    assert scenes, 'Kurs sollte mindestens eine Szene haben'
    total = sum(len(sc['slides']) for sc in scenes)
    assert total > 0
    # Jede Szene hat einen Namen und eine Folienliste.
    for sc in scenes:
        assert isinstance(sc['name'], str)
        assert isinstance(sc['slides'], list)


def test_slide_content_returns_items_and_optional_audio(fixture_ats: str) -> None:
    with zipfile.ZipFile(fixture_ats) as z:
        scenes = walk_course(z)
    # erste echte (nicht-exam) Folie suchen
    first_ata = None
    for sc in scenes:
        for s in sc['slides']:
            if s.get('ata'):
                first_ata = s['ata']
                break
        if first_ata:
            break
    assert first_ata is not None
    items, audio = slide_content(first_ata)
    assert isinstance(items, list)
    # items sind nach Layer sortiert
    layers = [it[0] for it in items]
    assert layers == sorted(layers)
    # kinds nur aus bekannter Menge
    assert all(it[1] in ('image', 'text') for it in items)


def test_thumbnail_returns_bytes_or_none(fixture_ats: str) -> None:
    with zipfile.ZipFile(fixture_ats) as z:
        scenes = walk_course(z)
    for sc in scenes:
        for s in sc['slides']:
            if s.get('ata'):
                t = thumbnail(s['ata'])
                assert t is None or (isinstance(t, bytes) and t[:8] == b'\x89PNG\r\n\x1a\n')
                return
