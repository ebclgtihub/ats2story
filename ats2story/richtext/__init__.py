#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""richtext — imc richText -> Blöcke und Blöcke -> Storyline fmtText."""
from __future__ import annotations

from .formatter import fmt_document, fmt_line_spacing, fmt_size, norm_color
from .parser import (
    BR_STARTS_BLOCK,
    METRIC_EQUIVALENTS,
    inline_blocks,
    inline_runs,
    map_font,
    parse_richtext,
)

__all__ = ['BR_STARTS_BLOCK', 'METRIC_EQUIVALENTS', 'fmt_document',
           'fmt_line_spacing', 'fmt_size', 'inline_blocks', 'inline_runs',
           'map_font', 'norm_color', 'parse_richtext']
