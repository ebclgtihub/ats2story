#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shape-Fragment-Builder (pic/textBox/sound/rels/slide) aus Stencils.

Reine Funktionen über der Vorlage (``tpl``). Die Geometrie-Transform
(``rect_transform``) ist injizierbar, damit geometry='fill' durchgereicht
werden kann.
"""
from __future__ import annotations

import html
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..geometry import Rect, fit_rect
from ..guid import b62, newg, relid, reguid
from ..richtext import fmt_document

if TYPE_CHECKING:
    from .template import Template

RectTransform = Callable[[float, float, float, float], Rect]
#: Ein Block ist eine Liste von (text, style_dict)-Runs.
Block = list

#: Storyline-Sentinel für „keine Rotation" (``rot="-1"`` in allen Referenz-
#: dateien; gedrehte Shapes tragen dort den Winkel in GRAD, z.B. ``rot="90"``).
NO_ROTATION = '-1'

#: Alpha-Skala in Storyline-Farben: ``<alpha val="100000" />`` = deckend.
ALPHA_FULL = 100000


def _rot_attr(rotation: float | None) -> str:
    """imc-Rotation (Grad) -> Storyline-``rot``-Wert (``-1`` = keine)."""
    try:
        deg = float(rotation or 0)
    except (TypeError, ValueError):
        return NO_ROTATION
    deg = round(deg) % 360
    return NO_ROTATION if deg == 0 else str(deg)


def _set_rot(frag: str, tag: str, rotation: float | None) -> str:
    """``rot``-Attribut im öffnenden ``tag`` von ``frag`` setzen."""
    return re.sub(rf'(<{tag}\b[^>]*?) rot="[^"]*"',
                  rf'\g<1> rot="{_rot_attr(rotation)}"', frag, count=1)


def _clr(hexcol: str, alpha: float = 100.0) -> str:
    """``#RRGGBB`` (+ Deckkraft in Prozent) -> Storyline-``<clr>``-Fragment."""
    val = (hexcol or '#000000').lstrip('#').upper()[:6].rjust(6, '0')
    a = max(0, min(ALPHA_FULL, int(round(ALPHA_FULL * (alpha if alpha is not None else 100) / 100))))
    inner = f'<srgbClr val="{val}" />' + ('' if a >= ALPHA_FULL else f'<alpha val="{a}" />')
    return f'<clr>{inner}</clr>'


def _apply_bg(frag: str, fill: str | None, stroke: tuple | None,
              opacity: float = 100.0) -> str:
    """Füllung/Rahmen im ``<bG>`` eines Shapes setzen (sonst bleibt es leer).

    Das Stencil trägt ``<noFill /><noLine />``; echte Storyline-Dateien nutzen
    an derselben Stelle ``<solidFill><clr>…</clr></solidFill>`` bzw.
    ``<solidLine><clr>…</clr></solidLine>`` plus die Breite im folgenden
    ``<lineStyle w="…">``.
    """
    if fill:
        frag = frag.replace('<noFill />', f'<solidFill>{_clr(fill, opacity)}</solidFill>', 1)
    if stroke:
        color, width = stroke
        frag = frag.replace('<noLine />', f'<solidLine>{_clr(color, opacity)}</solidLine>', 1)
        frag = re.sub(r'(<lineStyle\b[^>]*?) w="[^"]*"',
                      rf'\g<1> w="{max(1, int(round(width)))}"', frag, count=1)
    return frag


def build_pic(tpl: 'Template', e: dict, rect: Rect, name: str, zo: int, sid: int,
              dur: int, opacity: int = 100,
              rect_transform: RectTransform = fit_rect,
              rotation: float = 0) -> str:
    """<pic>-Fragment für ein Medium ``e`` an ``rect`` (imc-Koordinaten).

    ``opacity`` ist bereits in das Bild eingerechnet (siehe
    :func:`ats2story.media.apply_opacity`) und dient hier nur der Signatur-
    Kompatibilität; ``rotation`` ist der imc-Winkel in Grad.
    """
    p = reguid(tpl.pic_stencil, frozenset())   # ALLE GUIDs frisch (pro Klon eindeutig)
    p = _set_rot(p, 'pic', rotation)
    # assetG NACH reguid setzen -> auf mein Medium
    p = re.sub(r'(<pic\b[^>]*?)\sassetG="[0-9a-fA-F-]{36}"',
               rf'\g<1> assetG="{e["guid"]}"', p, count=1)
    p = re.sub(r'(<pic\b[^>]*?) id="\d+"', rf'\g<1> id="{sid}"', p, count=1)
    p = re.sub(r'(<pic\b[^>]*?) name="[^"]*"',
               r'\g<1> name="' + html.escape(name[:60]) + '"', p, count=1)
    p = re.sub(r'(<pic\b[^>]*?) zOrder="\d+"', rf'\g<1> zOrder="{zo}"', p, count=1)
    L, T, R, B = rect_transform(*rect)
    p = re.sub(r'<loc\b[^>]*/>', f'<loc l="{L:.3f}" t="{T:.3f}" r="{R:.3f}" b="{B:.3f}" />', p, count=1)
    p = re.sub(r'<sourceRect\b[^>]*/>',
               f'<sourceRect l="0" t="0" r="{e["w"]}" b="{e["h"]}" />', p, count=1)
    p = re.sub(r'(<tmCtx\b[^>]*?) dur="\d+"', rf'\g<1> dur="{dur}"', p)
    p = re.sub(r'(<sndTmCtx\b[^>]*?) dur="\d+"', rf'\g<1> dur="{dur}"', p)
    p = re.sub(r'<str>[0-9A-Za-z]{11}</str>', f'<str>{b62(uuid.uuid4().int)[:11]}</str>', p, count=1)
    return p


def build_textbox(tpl: 'Template', blocks: list[Block], rect: Rect, align: str,
                  zo: int, sid: int, atsrect: bool = False,
                  rect_transform: RectTransform = fit_rect,
                  name: str = 'Text', rotation: float = 0,
                  line_height: float | None = None,
                  fill: str | None = None, stroke: tuple | None = None,
                  opacity: float = 100.0) -> str:
    """<textBox>-Fragment mit fmtText aus ``blocks``.

    ``rotation`` (Grad), ``line_height`` (imc-Prozent) und ``fill``/``stroke``
    (Kastenfüllung und -rahmen) kommen direkt aus dem imc-Textelement.

    ``autoFit`` bleibt bewusst auf dem Stencil-Wert ``resize``: imc setzt zwar
    durchgehend ``autoSize="false"`` (fester Kasten), aber unsere Schrift- und
    Fontersetzung ist nicht pixelgenau — ein fixer Kasten würde Text abschneiden,
    ``resize`` verliert im Zweifel nichts.
    """
    tb = reguid(tpl.tb_stencil, frozenset())
    tb = _set_rot(tb, 'textBox', rotation)
    tb = _apply_bg(tb, fill, stroke, opacity)
    tb = re.sub(r'(<textBox\b[^>]*?) id="\d+"', rf'\g<1> id="{sid}"', tb, count=1)
    tb = re.sub(r'(<textBox\b[^>]*?) name="[^"]*"',
                r'\g<1> name="' + html.escape((name or 'Text')[:60]) + '"', tb, count=1)
    tb = re.sub(r'(<textBox\b[^>]*?) zOrder="\d+"', rf'\g<1> zOrder="{zo}"', tb, count=1)
    if atsrect:
        L, T, R, B = rect_transform(*rect)
    else:
        L, T, R, B = rect
    tb = re.sub(r'<loc\b[^>]*/>', f'<loc l="{L:.3f}" t="{T:.3f}" r="{R:.3f}" b="{B:.3f}" />', tb, count=1)
    doc = fmt_document(blocks, align, line_height)
    tb = re.sub(r'<text>.*?</text>', '<text>' + doc.replace('\\', r'\\') + '</text>',
                tb, count=1, flags=re.S)
    tb = re.sub(r'<fmtText>.*?</fmtText>', '<fmtText>' + doc.replace('\\', r'\\') + '</fmtText>',
                tb, count=1, flags=re.S)
    tb = re.sub(r'<str>[0-9A-Za-z]{11}</str>', f'<str>{b62(uuid.uuid4().int)[:11]}</str>', tb, count=1)
    return tb


def build_sound(tpl: 'Template', e: dict, dur: int, zo: int, sid: int) -> str:
    """<sound>-Fragment für ein Audio-Medium ``e`` (Auto-Play ab 0)."""
    s = reguid(tpl.snd_stencil, frozenset())
    s = re.sub(r'(<sound\b[^>]*?)\sassetG="[0-9a-fA-F-]{36}"',
               rf'\g<1> assetG="{e["guid"]}"', s, count=1)
    s = re.sub(r'(<sound\b[^>]*?) id="\d+"', rf'\g<1> id="{sid}"', s, count=1)
    s = re.sub(r'(<sound\b[^>]*?) zOrder="\d+"', rf'\g<1> zOrder="{zo}"', s, count=1)
    s = re.sub(r'(<sndTmCtx\b[^>]*?) dur="\d+"', rf'\g<1> dur="{e["dur"] or dur}"', s)
    s = re.sub(r'(<sndTmCtx\b[^>]*?) start="\d+"', r'\g<1> start="0"', s)
    s = re.sub(r'<str>[0-9A-Za-z]{11}</str>', f'<str>{b62(uuid.uuid4().int)[:11]}</str>', s, count=1)
    return s


def build_rels(entries: list[dict]) -> str:
    """slide.xml.rels: Media-Relationships für die genutzten Medien."""
    rels = ['﻿<?xml version="1.0" encoding="utf-8"?>'   # BOM wie alle Vorlagen-.rels
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for e in entries:
        rels.append(f'<Relationship Type="media" Target="/story/media/{e["fname"]}" Id="{relid()}" />')
    rels.append('</Relationships>')
    return ''.join(rels)


def assemble_slide(tpl: 'Template', shapes: list[str], name: str, dur: int) -> str:
    """Slide-Skelett scoped-reguiden, Folien-Attribute setzen, Shapes einsetzen."""
    sk = tpl.slide_skeleton
    sk = reguid(sk, tpl.preserve)   # externe Refs bleiben
    sld_g = newg()
    sk = re.sub(r'(<sld\b[^>]*?) g="[0-9a-fA-F-]{36}"', rf'\g<1> g="{sld_g}"', sk, count=1)
    sk = re.sub(r'(<sld\b[^>]*?) verG="[0-9a-fA-F-]{36}"', rf'\g<1> verG="{newg()}"', sk, count=1)
    sk = re.sub(r'(<sld\b[^>]*?) id="\d+"', r'\g<1> id="0"', sk, count=1)  # Vorlage: alle id=0
    sk = re.sub(r'(<sld\b[^>]*?) name="[^"]*"', r'\g<1> name="' + html.escape(name[:80]) + '"', sk, count=1)
    sk = re.sub(r'(<tmProps\b[^>]*?) min="\d+"', rf'\g<1> min="{dur}"', sk, count=1)
    sk = sk.replace('{SHAPES}', ''.join(shapes))
    return sk
