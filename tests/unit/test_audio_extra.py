#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zusätzliche Audio-Tests (WAV->MP3, ID3, mp3_duration_ms)."""
from __future__ import annotations

import io
import wave

import pytest

from ats2story.media import mp3_duration_ms, wav_to_mp3
from ats2story.media.audio import mp3_info
from ats2story.media.pool import MediaPool


def _wav_bytes(seconds: float = 0.1, sr: int = 44100, ch: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b'\x00\x00' * int(sr * seconds) * ch)
    return buf.getvalue()


def test_wav_to_mp3_produces_mp3() -> None:
    pytest.importorskip('lameenc')
    mp3 = wav_to_mp3(_wav_bytes())
    # MP3 beginnt mit Sync (0xFF 0xEx) oder ID3.
    assert mp3[:3] == b'ID3' or (mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0)
    assert len(mp3) > 0


def test_mp3_duration_ms_skips_id3_header() -> None:
    # ID3v2-Header (size 0) + ein gültiger MPEG1-Frame.
    id3 = b'ID3\x03\x00\x00\x00\x00\x00\x00'
    frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b'\x00' * 413
    assert mp3_duration_ms(id3 + frame) > 0


def test_mp3_info_ignores_invalid_bitrate_index() -> None:
    # bri=15 (0xF) ist ungültig -> Frame wird übersprungen, keine Dauer.
    bad = bytes([0xFF, 0xFB, 0xF0, 0x00]) + b'\x00' * 100
    dur, _sr, _ch, scnt = mp3_info(bad)
    assert dur == 0
    assert scnt == 0


def test_pool_add_audio_wav_path() -> None:
    pytest.importorskip('lameenc')
    pool = MediaPool()
    e = pool.add_audio(_wav_bytes(), 'Narration')
    assert e is not None
    assert e['audio'] is True
    assert e['ext'] == 'mp3'
    assert len(pool.audio_xml) == 1


def test_pool_add_audio_rejects_garbage() -> None:
    pool = MediaPool()
    # RIFF-Header aber kaputter Body -> wav_to_mp3 wirft -> None.
    e = pool.add_audio(b'RIFFxxxxWAVEjunk', 'bad')
    assert e is None
