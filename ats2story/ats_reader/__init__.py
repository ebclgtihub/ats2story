#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ats_reader — Lesen/Parsen von imc Content Studio .ats/.ata-Dateien."""
from __future__ import annotations

from ._ns import NS
from .canvas import DEFAULT_CANVAS, detect_canvas
from .slide_parser import cp, rect_of, slide_content, slide_duration_ms
from .thumbnail import thumbnail
from .walker import course_background, walk_course

__all__ = ['DEFAULT_CANVAS', 'NS', 'course_background', 'cp', 'detect_canvas',
           'rect_of', 'slide_content', 'slide_duration_ms', 'thumbnail',
           'walk_course']
