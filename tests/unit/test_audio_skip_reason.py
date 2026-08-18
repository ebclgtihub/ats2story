#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Übersprungener Ton muss seinen Grund mitliefern.

Anlass: imc legt die Sprecheraufnahmen als WAV ab, Storyline braucht MP3.
Fehlt der Encoder (``lameenc``), verschwand der Ton lautlos — der Bericht
sagte nur „Audio nicht übernommen", ohne dass die Ursache erkennbar war.
"""
from __future__ import annotations

import collections
import types

import pytest

from ats2story import converter
from ats2story.media import pool as pool_mod


@pytest.fixture()
def wav() -> bytes:
    """Kopf reicht — der Encoder wird im Test ohnehin ersetzt."""
    return b'RIFF' + b'\0' * 40


def test_missing_encoder_is_named(monkeypatch, wav: bytes) -> None:
    def boom(_raw):
        raise ModuleNotFoundError("No module named 'lameenc'")

    monkeypatch.setattr(pool_mod, 'wav_to_mp3', boom)
    p = pool_mod.MediaPool()
    assert p.add_audio(wav, 'sprecher_144.wav') is None
    assert 'lameenc' in (p.last_audio_error or '')


def test_other_failures_keep_their_message(monkeypatch, wav: bytes) -> None:
    def boom(_raw):
        raise ValueError('kaputter WAV-Kopf')

    monkeypatch.setattr(pool_mod, 'wav_to_mp3', boom)
    p = pool_mod.MediaPool()
    assert p.add_audio(wav, 'x.wav') is None
    assert 'kaputter WAV-Kopf' in (p.last_audio_error or '')


def test_reason_stands_before_the_slide_list() -> None:
    """Die Folienliste sagt nur DASS etwas fehlt — der Grund gehört nach vorn."""
    builder = types.SimpleNamespace(
        skipped_img_log=[], skipped_audio_log=[(1, 'Folie A', 'MP3-Encoder fehlt (lameenc)'),
                                               (2, 'Folie B', 'MP3-Encoder fehlt (lameenc)')],
        ocr_replaced=0, skipped_img=0, skipped_slides=0, skipped_audio=2,
        fonts=collections.Counter())
    stats = converter._make_stats('k.story', 2, [], types.SimpleNamespace(files={}),
                                  0, builder, 0.0, None)
    assert stats.skipped_detail[0].startswith('Grund: ')
    assert 'lameenc' in stats.skipped_detail[0]
    # ...und nur EINMAL, auch wenn mehrere Folien betroffen sind.
    assert sum(1 for line in stats.skipped_detail if line.startswith('Grund: ')) == 1
    assert len(stats.skipped_detail) == 3
