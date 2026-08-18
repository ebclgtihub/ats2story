#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blöcke -> Storyline fmtText (Document/Block/Span), doppelt-escaped."""
from __future__ import annotations

import html
import re

#: Ein Run ist (text, style_dict); ein Block eine Liste von Runs.
Run = tuple[str, dict]
Block = list[Run]

_JUST = {'left': 'Left', 'center': 'Center', 'right': 'Right', 'justify': 'Justified'}


def norm_color(c: str | None) -> str:
    """Farb-String -> normalisiertes ``#RRGGBB`` (Großbuchstaben)."""
    c = (c or '#000000').strip()
    if c.startswith('#'):
        c = c[1:]
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    if not re.fullmatch(r'[0-9a-fA-F]{6}', c):
        c = '000000'
    return '#' + c.upper()


def fmt_size(size: object, default: str = '18') -> str:
    """Schriftgröße -> Storyline-Attributwert (ganzzahlig, wenn möglich).

    Nimmt Zahlen wie ``13.0``/``13.5`` und Strings (auch ``"18px"``) entgegen;
    ``13.0`` wird zu ``"13"``, damit die fmtText-Attribute so aussehen wie die
    von Storyline selbst geschriebenen.
    """
    try:
        val = float(str(size).strip().rstrip('px').strip())
    except (TypeError, ValueError):
        return default
    if val <= 0:
        return default
    return str(int(val)) if abs(val - round(val)) < 0.05 else f'{val:.1f}'


#: Storyline-Wert für einfachen Abstand (``LineSpacingRule="Single"``).
LINE_SPACING_BASE = 20


def fmt_line_spacing(line_height: float | None,
                     font_pt: float | None = None) -> tuple[str, str]:
    """imc ``lineHeight`` (Prozent) -> ``(LineSpacingRule, LineSpacing)``.

    imc rechnet CSS-artig: der Zeilenabstand ist ``Schriftgröße x lineHeight``.
    Im imc-Rendering des Beispielkurses sind das bei ``fontSize="13"`` und
    ``lineHeight="125"`` nachgemessen **16 px** (= 13 x 1,25) — NICHT das
    1,25-fache von Storylines eigenem „einfachem" Abstand (der schon ~1,2 em
    beträgt). ``Multiple`` würde die Leerräume also doppelt zählen und den
    Textblock rund 19 % zu hoch machen.

    Deshalb ``Exactly`` mit dem absoluten Wert in Punkt — die Form, die auch in
    den Storyline-Referenzdateien vorkommt (z.B. ``Exactly/18.75`` = 15 x 1,25).
    Ohne bekannte Schriftgröße oder bei 100 % bleibt es bei ``Single``.
    """
    try:
        pct = float(line_height) if line_height is not None else 100.0
    except (TypeError, ValueError):
        pct = 100.0
    try:
        size = float(font_pt) if font_pt else 0.0
    except (TypeError, ValueError):
        size = 0.0
    if size <= 0 or not (10.0 <= pct <= 500.0) or abs(pct - 100.0) < 0.5:
        return ('Single', str(LINE_SPACING_BASE))
    val = size * pct / 100.0
    return ('Exactly', str(int(val)) if abs(val - round(val)) < 0.05 else f'{val:.2f}')


def _max_size(runs: Block) -> float:
    """Größte Schriftgröße (pt) eines Blocks — bestimmt dessen Zeilenhöhe."""
    sizes = []
    for _text, st in runs:
        try:
            sizes.append(float(str(st.get('size', 0)).strip().rstrip('px') or 0))
        except (TypeError, ValueError):
            continue
    return max(sizes) if sizes else 0.0


def fmt_document(blocks: list[Block], align: str = 'left',
                 line_height: float | None = None) -> str:
    """Blöcke -> escaptes Storyline-Document/Block/Span (für <text> UND <fmtText>).

    RICH-Form exakt wie echte Storyline-fmtTexts (alle Block/ListStyle/Span-
    Attribute + <Shadow>) — fehlende non-nullable Felder => 'invalid or corrupt'.
    ``line_height`` ist der imc-Zeilenabstand in Prozent.
    """
    just = _JUST.get((align or 'left').lower(), 'Left')
    out = ['<Document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><Content>']
    for runs in blocks:
        # Zeilenabstand JE BLOCK aus dessen größter Schrift (die bestimmt die
        # Zeilenhöhe) — ein Block kann Runs unterschiedlicher Größe enthalten.
        ls_rule, ls_val = fmt_line_spacing(line_height, _max_size(runs))
        out.append('<Block><Style FlowDirection="LeftToRight" LeadingMargin="0" '
                   'TrailingMargin="0" FirstLineMargin="0" '
                   f'Justification="{just}" DefaultTabStop="48" ListLevel="0" '
                   f'LineSpacingRule="{ls_rule}" LineSpacing="{ls_val}" '
                   'SpacingBefore="0" SpacingAfter="0">'
                   '<ListStyle ListType="None" ListTypeFormat="Parentheses" Start="0" '
                   'Color="#000000,00" Size="100" BulletFont="Arial" /></Style>')
        for text, st in runs:
            esc = html.escape(text, quote=True)
            col = norm_color(st['color'])
            attrs = (f'FontFamily="{html.escape(st["fam"])}" FontSize="{fmt_size(st["size"])}" '
                     f'FontIsBold="{"True" if st["bold"] else "False"}" '
                     f'FontIsItalic="{"True" if st["ital"] else "False"}" '
                     f'FontIsUnderline="{"True" if st["under"] else "False"}" '
                     'FontIsStrikeout="False" UnderlineStyle="Normal" '
                     f'ForegroundColor="{col}" BackgroundColor="#000000,00" '
                     'UnderlineColor="#000000,00" Elevation="Normal" Spacing="0" '
                     'IgnoreKerningTable="False" DisplayCase="AsIs" LanguageId="0" '
                     f'LinkColor="{col}"')
            out.append(f'<Span Text="{esc}"><Style {attrs}>'
                       '<Shadow Offset="0x0" Color="#FFFFFF,00" /></Style></Span>')
        out.append('</Block>')
    out.append('</Content></Document>')
    doc = ''.join(out)
    return doc.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
