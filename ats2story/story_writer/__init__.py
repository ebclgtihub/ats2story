#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""story_writer — Vorlage, Folien-Builder und OPC-Paket-Schreiben."""
from __future__ import annotations

from .backgrounds import clean_backgrounds
from .builder import MIN_DUR, Builder
from .opc_writer import write_story_package
from .patch import (
    add_media_pool,
    build_story_rels,
    build_summary,
    patch_story_xml,
    set_story_size,
    strip_quiz,
)
from .template import Template

__all__ = [
    'MIN_DUR',
    'Builder',
    'Template',
    'add_media_pool',
    'build_story_rels',
    'build_summary',
    'clean_backgrounds',
    'patch_story_xml',
    'set_story_size',
    'strip_quiz',
    'write_story_package',
]
