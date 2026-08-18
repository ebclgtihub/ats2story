#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media — Medienpool, Bild-Re-Encode und Audio-Analyse."""
from __future__ import annotations

from .audio import mp3_duration_ms, mp3_info, wav_to_mp3
from .image import EncodedImage, apply_opacity, reencode_image
from .pool import MediaPool

__all__ = [
    'apply_opacity',
    'EncodedImage',
    'MediaPool',
    'mp3_duration_ms',
    'mp3_info',
    'reencode_image',
    'wav_to_mp3',
]
