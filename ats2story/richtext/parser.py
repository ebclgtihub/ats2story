#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""imc richText (HTML-Fragment) -> Blöcke aus (text, style)-Runs."""
from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Protocol

Style = dict
Run = tuple[str, Style]
Block = list[Run]

#: Storyline kennt KEINEN weichen Zeilenumbruch: in einer von Storyline
#: SELBST geschriebenen Datei (714 Textfelder) steht in ``<Span Text="...">``
#: kein einziges Steuerzeichen und es gibt kein ``<Br>``-Tag — jede Zeile ist
#: ein eigener ``<Block>`` (Ø 1,6 Blöcke je Textfeld). imc-``<br>`` wird
#: deshalb wie ``<p>`` zu einer BLOCKGRENZE; mit ``SpacingBefore/After="0"``
#: sieht das aus wie ein Zeilenumbruch. (Ein zuvor erwogenes U+2028 kommt in
#: Storyline-Dateien NICHT vor und wäre geraten gewesen.)
BR_STARTS_BLOCK = True

#: Metrisch identische Schriftersatz-Paare. imc-Kurse sind in Arimo gesetzt —
#: einer der Google-Croscore-Klone, die zeichenbreitengleich zu den
#: Microsoft-Kernschriften entworfen wurden. Auf einem Storyline-Rechner ist
#: Arimo praktisch nie installiert; Storyline ersetzt sie dann durch eine
#: BELIEBIGE Fallback-Schrift mit anderen Breiten, und der Umbruch verschiebt
#: sich. Die Zuordnung auf das metrische Gegenstück hält das Layout stabil
#: (Arial kommt in Storyline-Dateien selbst am häufigsten vor).
METRIC_EQUIVALENTS = {
    'arimo': 'Arial',
    'liberation sans': 'Arial',
    'tinos': 'Times New Roman',
    'liberation serif': 'Times New Roman',
    'cousine': 'Courier New',
    'liberation mono': 'Courier New',
    'carlito': 'Calibri',
    'caladea': 'Cambria',
}


def map_font(name: str | None, default: str = 'Arial') -> str:
    """Schriftname -> auf dem Zielrechner vorhandenes, metrisch gleiches Pendant.

    Unbekannte Namen bleiben unverändert — ersetzt wird nur, was nachweislich
    zeichenbreitengleich ist (:data:`METRIC_EQUIVALENTS`).
    """
    fam = (name or '').strip().strip('"\'')
    if not fam:
        return default
    return METRIC_EQUIVALENTS.get(fam.lower(), fam)


class _Attributed(Protocol):
    """Minimaler Element-Kontrakt: nur ``.get(name, default)`` wird benötigt
    (ElementTree-Element ODER ein beliebiges duck-typed Objekt)."""

    def get(self, key: str, default: object = None) -> object: ...


def parse_richtext(richhtml: str | None, t: _Attributed,
                   font_pt: Callable[[object], float] | None = None) -> list[Block]:
    """imc richText (<p>, <br>, inline-tags) + Element-Attribute -> Liste Blöcke.

    ``t`` ist das .ata-XML-Element (liest fontFamily/fontSize/textColor/...).
    Jeder Block ist eine Liste von ``(text, style_dict)``-Runs.

    ``font_pt`` rechnet eine imc-Schriftgröße (PIXEL auf dem imc-Canvas) in
    Storyline-PUNKT um — üblicherweise :meth:`ats2story.geometry.Geometry.font_pt`.
    Ohne Callback bleibt die Zahl unverändert (Alt-Verhalten für Aufrufer, die
    keine Geometrie kennen).
    """
    conv = font_pt if font_pt is not None else (lambda v: v)
    fam = map_font(t.get('fontFamily'))
    size = conv(t.get('fontSize') or '18')
    color = (t.get('textColor') or '#000000')
    bold = (t.get('fontBold') == 'true')
    ital = (t.get('fontItalic') == 'true')
    under = (t.get('fontUnderline') == 'true')
    base = dict(fam=fam, size=size, color=color, bold=bold, ital=ital, under=under)

    htmltext = richhtml or ''
    # <p ...> als Blockgrenze, </p> entfernen
    parts = re.split(r'<\s*p\b[^>]*>', htmltext, flags=re.I)
    blocks: list[Block] = []
    for part in parts:
        part = re.sub(r'</\s*p\s*>', '', part, flags=re.I)
        if part is None:
            continue
        # <br> beendet den Block und beginnt einen neuen (s. BR_STARTS_BLOCK);
        # der Stil-Stack läuft dabei weiter, ein <br> INNERHALB eines <span>
        # verliert dessen Formatierung also nicht.
        blocks.extend(inline_blocks(part, base, conv))

    def empty(blk: Block) -> bool:
        return all(not txt.strip() for txt, _ in blk)

    while len(blocks) > 1 and empty(blocks[0]):
        blocks.pop(0)
    while len(blocks) > 1 and empty(blocks[-1]):
        blocks.pop()
    if not blocks:
        blocks = [[('', base)]]
    return blocks


def _apply_css(st: Style, css: str, conv: Callable[[object], float]) -> None:
    """CSS-Deklarationen eines ``<span style="...">`` auf ``st`` anwenden.

    Wichtig: imc schreibt ausdrücklich auch die NEUTRALEN Werte
    (``font-weight: normal``, ``font-style: normal``, ``text-decoration: none``).
    Die müssen den Element-Basisstil ZURÜCKSETZEN — sonst bleibt eine fett
    gesetzte Textbox durchgehend fett, obwohl der Span das Gegenteil sagt.
    """
    cm = re.search(r'(?<![-\w])color\s*:\s*([^;]+)', css, re.I)
    if cm:
        st['color'] = cm.group(1).strip()
    fm = re.search(r'font-size\s*:\s*([0-9.]+)', css, re.I)
    if fm:
        st['size'] = conv(fm.group(1))
    fam = re.search(r'font-family\s*:\s*([^;]+)', css, re.I)
    if fam:
        name = fam.group(1).strip().split(',')[0]
        if name.strip():
            st['fam'] = map_font(name)
    wm = re.search(r'font-weight\s*:\s*([a-z0-9]+)', css, re.I)
    if wm:
        w = wm.group(1).lower()
        st['bold'] = w == 'bold' or w == 'bolder' or (w.isdigit() and int(w) >= 600)
    sm = re.search(r'font-style\s*:\s*([a-z]+)', css, re.I)
    if sm:
        st['ital'] = sm.group(1).lower() in ('italic', 'oblique')
    dm = re.search(r'text-decoration(?:-line)?\s*:\s*([a-z\s-]+)', css, re.I)
    if dm:
        st['under'] = 'underline' in dm.group(1).lower()


def inline_runs(seg: str, base: Style,
                font_pt: Callable[[object], float] | None = None) -> Block:
    """Einfacher Inline-Parser: <b>/<strong>, <i>/<em>, <u>, <span style=...>.

    Gibt Liste ``(text, style)`` zurück (``<br>`` bleibt hier ohne Wirkung —
    Blockgrenzen macht :func:`inline_blocks`). Unbekannte Tags werden ignoriert.
    ``font_pt`` rechnet ``font-size``-Angaben (px) in Punkt um.
    """
    return [run for blk in inline_blocks(seg, base, font_pt) for run in blk]


def inline_blocks(seg: str, base: Style,
                  font_pt: Callable[[object], float] | None = None) -> list[Block]:
    """Wie :func:`inline_runs`, beginnt bei ``<br>`` aber einen NEUEN Block.

    Der Stil-Stack läuft über die Grenze weiter: ein ``<br>`` mitten in einem
    ``<span style="...">`` behält dessen Formatierung für die Folgezeile.
    """
    conv = font_pt if font_pt is not None else (lambda v: v)
    blocks: list[Block] = []
    runs: Block = []
    stack: list[Style] = [dict(base)]
    buf: list[str] = []

    def flush() -> None:
        if buf:
            runs.append((''.join(buf), dict(stack[-1])))
            buf.clear()

    for m in re.finditer(r'<[^>]+>|[^<]+', seg):
        tok = m.group(0)
        if not tok.startswith('<'):
            buf.append(html.unescape(tok))
            continue
        flush()
        low = tok.lower()
        closing = low.startswith('</')
        name_m = re.match(r'</?\s*([a-z0-9]+)', low)
        name = name_m.group(1) if name_m else ''
        if name == 'br' and not closing:
            blocks.append(runs)
            runs = []
            continue
        if closing:
            if len(stack) > 1:
                stack.pop()
        else:
            st = dict(stack[-1])
            if name in ('b', 'strong'):
                st['bold'] = True
            elif name in ('i', 'em'):
                st['ital'] = True
            elif name == 'u':
                st['under'] = True
            elif name == 'span':
                sm = re.search(r'style\s*=\s*"([^"]*)"', tok, re.I)
                if sm:
                    _apply_css(st, html.unescape(sm.group(1)), conv)
            if not low.endswith('/>'):
                stack.append(st)
    flush()
    blocks.append(runs)
    return [blk if blk else [('', dict(base))] for blk in blocks]
