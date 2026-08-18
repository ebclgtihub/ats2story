#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ersetzt Vorlagen-Hintergrundbilder und -Farbflächen durch reines Weiß."""
from __future__ import annotations

import hashlib
import io
import logging
import re
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from .template import Template

log = logging.getLogger(__name__)


class CleanResult(int):
    """Ergebnis von :func:`clean_backgrounds`: der *Gesamt*-Zähler (Bilder +
    Flächen) als ``int`` — abwärtskompatibel zu ``n = clean_backgrounds(...)``
    und ``n > 0`` — mit zusätzlicher Aufschlüsselung über ``.images``/``.fills``
    (für getrennte Fortschrittsmeldungen, T6).
    """

    images: int
    fills: int

    def __new__(cls, images: int, fills: int) -> 'CleanResult':
        self = super().__new__(cls, images + fills)
        self.images = images
        self.fills = fills
        return self


#: Weiße Ersatz-Farbe (self-closing, wie im Storyline-XML üblich).
_WHITE = '<srgbClr val="FFFFFF" />'

#: Inhalt eines ``<clr>…</clr>``-Wrappers (Farbe + evtl. ``<alpha>``/Modifier).
#: Nicht-gierig, damit bei mehreren ``<clr>`` je Element getrennt ersetzt wird.
_CLR_INNER = re.compile(r'<clr>(.*?)</clr>', re.S)

#: Behält eine evtl. vorhandene ``<alpha val="…" />`` (Transparenz erhalten).
_ALPHA_TAG = re.compile(r'<alpha\b[^>]*/>')

#: Ein vollständiges ``<solidFill>…</solidFill>`` (tag-lokal, nicht gierig).
_SOLID_FILL = re.compile(r'<solidFill>.*?</solidFill>', re.S)

#: Ein vollständiges ``<gradFill …>…</gradFill>`` (mit evtl. Attributen).
_GRAD_FILL = re.compile(r'<gradFill\b[^>]*>.*?</gradFill>', re.S)


def _white_clr(m: re.Match[str]) -> str:
    """Ersetzt den Farbteil eines ``<clr>``-Wrappers durch Weiß.

    Behält ein evtl. vorhandenes ``<alpha>`` (transparente/halbtransparente
    Flächen bleiben es), verwirft aber ``<srgbClr>``/``<schemeClr>``/``<shade>``/
    ``<tint>`` und setzt stattdessen reines Weiß. Ein leeres ``<clr />`` (kein
    Inhalt) bleibt unverändert — dort gibt es keine Farbe zu whiten.
    """
    inner = m.group(1)
    if not inner:                                  # <clr></clr> / <clr /> → nichts zu tun
        return m.group(0)
    alpha = _ALPHA_TAG.search(inner)
    body = _WHITE + (alpha.group(0) if alpha else '')
    return f'<clr>{body}</clr>'


#: Farb-Element (srgbClr/schemeClr): self-closing ODER mit Kindern (alpha/shade/tint).
_COLOR_EL = re.compile(r'<(srgbClr|schemeClr)\b[^>]*(?:/>|>.*?</\1>)', re.S)


def _white_color_element(colorel: str) -> str:
    """Weißt ein direktes Farb-Element (Form 2, ohne ``<clr>``-Wrapper).

    ``<alpha>`` (Transparenz) bleibt erhalten; ``<shade>``/``<tint>`` fällt weg
    (auf Weiß sinnlos → würde grau/getönt rendern).
    """
    alpha = _ALPHA_TAG.search(colorel)
    if alpha:
        return f'<srgbClr val="FFFFFF">{alpha.group(0)}</srgbClr>'
    return _WHITE


def _whiten_solid_fills(xml: str) -> tuple[str, int]:
    """Setzt die Farbe ALLER ``<solidFill>`` auf reines Weiß; ein evtl.
    ``<alpha>`` bleibt erhalten (transparente Flächen bleiben transparent).

    Deckt srgbClr, schemeClr UND shade/tint-Modifikatoren ab (``<clr><shade
    val="…"/></clr>`` etc.), indem der ``<clr>``-Inhalt komplett ersetzt wird.
    Färbt damit Hintergrund-Flächen UND dekorative Master/Layout-Formen
    (z.B. die grüne Footer-Leiste) weiß. Der eigentliche Folien-Inhalt liegt
    in den Folien-Parts, nicht hier, und bleibt unberührt.
    """
    n = 0

    def repl(sf: re.Match[str]) -> str:
        nonlocal n
        block = sf.group(0)
        # Form 1: Farbe im <clr>-Wrapper (echte Vorlagen nutzen nur diese, 623x).
        new_sf, c = _CLR_INNER.subn(_white_clr, block)
        if c:
            n += 1
            return new_sf
        # Form 2: Farbe als direktes Kind des <solidFill> (ohne <clr>-Wrapper).
        # In den Vorlagen nicht vorhanden, aber gültiges OOXML → defensiv weißen.
        m = _COLOR_EL.search(block)
        if m:
            n += 1
            return block[:m.start()] + _white_color_element(m.group(0)) + block[m.end():]
        return block

    out = _SOLID_FILL.sub(repl, xml)
    return out, n


def _whiten_grad_fills(xml: str) -> tuple[str, int]:
    """Weißt alle Farb-Stops in ``<gradFill>``-Verläufen (echte Master-BGs,
    z.B. ``slideMaster3.xml`` mit ``EFEFEF``→``D3D3D3``).

    Behält die Verlaufsstruktur (Stops/Positionen), setzt aber jeden Stop auf
    Weiß (``<clr>``-Inhalt → Weiß, ``<alpha>`` erhalten). So blitzt kein grauer
    Verlauf mehr durch, ohne riskante Struktur-Operationen.
    """
    n = 0

    def repl(gf: re.Match[str]) -> str:
        nonlocal n
        new_gf, c = _CLR_INNER.subn(_white_clr, gf.group(0))
        if c:
            n += 1
        return new_gf

    out = _GRAD_FILL.sub(repl, xml)
    return out, n


def _whiten_part(data: bytes, fn: str) -> tuple[bytes | None, int]:
    """Dekodiert einen XML-Part STRIKT als UTF-8, weißt solidFill+gradFill.

    Bei ungültigem UTF-8 wird geloggt und der Part übersprungen (``None``,
    ``0``) statt mit ``replace`` still korruptes XML zu re-encodieren (T6).
    """
    try:
        xml = data.decode('utf-8')
    except UnicodeDecodeError as ex:
        log.warning('clean_backgrounds: %s ist kein gültiges UTF-8 (%s) — übersprungen', fn, ex)
        return None, 0
    xml, n_solid = _whiten_solid_fills(xml)
    xml, n_grad = _whiten_grad_fills(xml)
    total = n_solid + n_grad
    if not total:
        return None, 0
    return xml.encode('utf-8'), total


def clean_backgrounds(tpl: 'Template') -> CleanResult:
    """Macht Folien-Hintergründe weiß: Hintergrund-BILDER (von slideMasters
    referenziert) UND alle FARBFLÄCHEN in Masters/Layouts (solidFill inkl.
    shade/tint + gradFill-Verläufe; dekorative Formen wie Footer-Leisten;
    transparente Flächen bleiben transparent).

    Zieht die mediaLst-md5 in ``tpl.story`` mit (sonst evtl. 'invalid or
    corrupt'). Rückgabe: :class:`CleanResult` — ein ``int`` (Gesamtzahl, abwärts-
    kompatibel) mit ``.images`` (gesäuberte Hintergrund-Bilder) und ``.fills``
    (gesäuberte Farbflächen-Elemente: solidFill + gradFill) für getrennte
    Fortschrittsmeldungen.
    """
    images = 0
    fills = 0

    # 1) Hintergrund-BILDER -> Weiß
    bg: set[str] = set()
    for fn, data in tpl.parts.items():
        if fn.startswith('story/slideMasters/_rels/') and fn.endswith('.rels'):
            for t in re.findall(r'Target="(/story/media/[^"]+)"', data.decode('utf-8', 'replace')):
                bg.add(t.lstrip('/'))
    for fn in bg:
        old = tpl.parts.get(fn)
        if not old:
            continue
        try:
            size = Image.open(io.BytesIO(old)).size
        except Exception:
            continue
        old_md5 = hashlib.md5(old).hexdigest()
        white = Image.new('RGB', size, (255, 255, 255))
        buf = io.BytesIO()
        if fn.lower().endswith('.png'):
            white.save(buf, 'PNG')
        else:
            white.save(buf, 'JPEG', quality=90)
        new = buf.getvalue()
        new_md5 = hashlib.md5(new).hexdigest()
        tpl.parts[fn] = new
        if old_md5 in tpl.keep_md5:
            tpl.keep_md5.discard(old_md5)
            tpl.keep_md5.add(new_md5)
        tpl.story = tpl.story.replace(old_md5, new_md5)   # mediaLst-Prüfsumme mitziehen
        images += 1

    # 2) FARBFLÄCHEN in Masters/Layouts -> Weiß (bg + dekorative Formen)
    for fn, data in list(tpl.parts.items()):
        if (fn.endswith('.xml') and '_rels/' not in fn
                and (fn.startswith('story/slideMasters/') or fn.startswith('story/slideLayouts/'))):
            new_xml, n = _whiten_part(data, fn)
            if new_xml is not None:
                tpl.parts[fn] = new_xml
                fills += n

    return CleanResult(images, fills)
