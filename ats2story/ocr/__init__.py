#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocr — Bild-Text-Erkennung (Tesseract) -> editierbare Storyline-Textblöcke."""
from __future__ import annotations

from . import config
from .blocks import ocr_textblocks
from .engine import _ocr_raw, _ocr_env, _flatten_gray, _text_color, ocr_lang

__all__ = [
    'config',
    'ocr_lang',
    'ocr_textblocks',
    '_ocr_env',
    '_ocr_raw',
    '_flatten_gray',
    '_text_color',
]
