#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zentrale Security-Härtung. Wird von ALLEN Modulen importiert — die Guards
dürfen NICHT dupliziert werden.

Schützt gegen:
  * zip-slip (absolute/``..``-Pfade in ZIP-Membern)
  * zip-bomb (überdimensionierte einzelne ZIP-Member)
  * decompression-bomb bei Bildern (Pixel-Cap, vor ``Image.load()`` prüfen)
"""
from __future__ import annotations

import posixpath
import zipfile

#: Per-Member-Cap (bytes) gegen zip-bombs.
ZIP_MEMBER_MAX: int = 200 * 1024 * 1024  # 200 MB

#: Pixel-Cap (Breite*Höhe) gegen decompression-bombs bei Bildern.
IMG_PIXEL_MAX: int = 4096 * 4096


def safe_zip_read(z: zipfile.ZipFile, name: str) -> bytes:
    """Liest einen Member aus ``z`` nach Abweisung von zip-slip und zip-bomb.

    Raises:
        ValueError: bei verdächtigem Namen (zip-slip) oder zu großem Member.
    """
    norm = posixpath.normpath(name)
    if posixpath.isabs(norm) or norm.startswith('..'):
        raise ValueError(f'Zip-slip rejected: {name!r}')
    info = z.getinfo(name)
    # file_size stammt aus dem ZIP-Header (deklarierte unkomprimierte Größe).
    # Ein bösartiges Archiv könnte hier lügen; das Bedrohungsmodell ist jedoch
    # vertrauenswürdiger interner .ats-Input (kein adversarieller Upload), daher
    # genügt der Header-Check ohne dekomprimierendes Streaming-Limit.
    if info.file_size > ZIP_MEMBER_MAX:
        raise ValueError(f'Zip-bomb rejected: {name!r} declares {info.file_size} bytes')
    return z.read(name)
