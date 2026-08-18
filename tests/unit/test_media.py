#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für das media-Paket."""
from __future__ import annotations

import io

from PIL import Image

from ats2story.media import MediaPool, mp3_info, reencode_image


def _png_bytes(size=(8, 8), color=(255, 0, 0, 255)) -> bytes:
    im = Image.new('RGBA', size, color)
    buf = io.BytesIO()
    im.save(buf, 'PNG', interlace=True)  # interlaced -> wird re-encodiert
    return buf.getvalue()


def _one_mp3_frame() -> bytes:
    """Minimaler MPEG1 LayerIII 128 kbit/s 44100 Hz Frame (Header genügt für mp3_info)."""
    # 0xFF FB = MPEG1 LayerIII no-CRC; 0x90 = 128kbit/44100; 0x00 = stereo
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    # frame length = 144*bitrate/srate = 144*128000/44100 = 417
    return header + b'\x00' * (417 - 4)


def test_mp3_info_parses_single_frame() -> None:
    dur, sr, ch, scnt = mp3_info(_one_mp3_frame())
    assert sr == 44100
    assert ch == 2
    assert scnt == 1152  # ein LayerIII-Frame
    assert dur > 0


def test_mp3_info_empty_returns_defaults() -> None:
    dur, sr, ch, scnt = mp3_info(b'')
    assert dur == 0
    assert scnt == 0


def test_reencode_image_png_roundtrip() -> None:
    enc = reencode_image(_png_bytes())
    assert enc is not None
    assert enc.ext == 'png'
    assert enc.mtype == 'Png'
    assert enc.width == 8 and enc.height == 8
    # re-encodiert -> dekodierbar
    assert Image.open(io.BytesIO(enc.data)).size == (8, 8)


def test_reencode_image_rejects_garbage() -> None:
    assert reencode_image(b'not an image at all') is None


def test_pool_dedup_by_md5() -> None:
    pool = MediaPool()
    raw = _png_bytes()
    e1 = pool.add_image(raw, 'Bild A')
    e2 = pool.add_image(raw, 'Bild B')  # identische Bytes -> dedup
    assert e1 is not None and e2 is not None
    assert e1['guid'] == e2['guid']
    assert len(pool.files) == 1
    assert len(pool.media_xml) == 1


def test_pool_image_entry_shape() -> None:
    pool = MediaPool()
    e = pool.add_image(_png_bytes(), 'X')
    assert e is not None
    for key in ('guid', 'fname', 'ext', 'md5', 'dur', 'audio', 'w', 'h'):
        assert key in e
    assert e['audio'] is False
    assert e['fname'].startswith('R') and e['fname'].endswith('.png')


def test_pool_entries_xml_media_before_audio() -> None:
    pool = MediaPool()
    pool.add_image(_png_bytes(), 'img')
    # entries_xml ist media_xml + audio_xml (Reihenfolge-Invariante)
    assert pool.entries_xml == pool.media_xml + pool.audio_xml
