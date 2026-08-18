#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erkennt den imc-Canvas (Bühnengröße) eines Kurses.

imc Content Studio rendert je nach Geräteprofil auf unterschiedliche Größen —
beobachtet: 1024x748 (DE-Kurs) und 950x630 (PL-Kurs). Das Geräteprofil selbst
steht nur als GUID im Kurs, die Maße stehen nirgends explizit. Zwei Signale
liefern sie trotzdem zuverlässig:

1. ``meta/thumbnail.png`` in jeder ``.ata`` ist ein 1:1-Rendering der Folie und
   damit exakt canvas-groß (in beiden Beispielkursen für ALLE Folien bestätigt).
2. Fallback: die maximale Ausdehnung aller ``rect``-Angaben über die Folien —
   eine untere Schranke, die auf gängige Profile gerundet wird.
"""
from __future__ import annotations

import io
import zipfile
from collections import Counter

from ..security import safe_zip_read
from ._ns import ET, NS

#: Fallback, wenn kein Signal auswertbar ist (bisheriges hart verdrahtetes Maß).
DEFAULT_CANVAS = (1024, 748)

#: Plausible Canvas-Grenzen — schützt vor Thumbnails, die keine Vollbild-
#: Renderings sind (Icons o.ä.).
_MIN_SIDE, _MAX_SIDE = 320, 4096

#: Bekannte imc-Geräteprofile; die Rect-Schranke wird auf das kleinste
#: Profil gerundet, das den Inhalt vollständig aufnimmt.
_KNOWN = ((950, 630), (1024, 748), (1024, 768), (1280, 720), (1280, 800))

#: So viele .ata werden je Kurs für die Erkennung angefasst (Mehrheitsentscheid).
_SAMPLE = 12


def _thumb_size(ata_bytes: bytes) -> tuple[int, int] | None:
    """Größe des ``meta/thumbnail.png`` einer .ata — ohne das Bild zu dekodieren."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ist Pflicht-Dependency
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(ata_bytes)) as ata:
            names = [n for n in ata.namelist()
                     if 'thumbnail' in n.lower() and n.lower().endswith('.png')]
            if not names:
                return None
            with Image.open(io.BytesIO(safe_zip_read(ata, names[0]))) as im:
                w, h = im.size          # nur Header, kein load()
    except Exception:
        return None
    if _MIN_SIDE <= w <= _MAX_SIDE and _MIN_SIDE <= h <= _MAX_SIDE:
        return (w, h)
    return None


def _rect_extent(ata_bytes: bytes) -> tuple[float, float]:
    """Maximale rechte/untere Kante aller ``rect``-Elemente einer .ata."""
    try:
        with zipfile.ZipFile(io.BytesIO(ata_bytes)) as ata:
            root = ET.fromstring(safe_zip_read(ata, 'document/document.xml'))
    except Exception:
        return (0.0, 0.0)
    mx = my = 0.0
    for r in root.iter(NS + 'rect'):
        try:
            x, y = float(r.get('x', 0)), float(r.get('y', 0))
            w, h = float(r.get('width', 0)), float(r.get('height', 0))
        except (TypeError, ValueError):
            continue
        mx, my = max(mx, x + w), max(my, y + h)
    return (mx, my)


def _round_to_profile(w: float, h: float) -> tuple[int, int] | None:
    """Kleinstes bekanntes Profil, das (w,h) aufnimmt — sonst None."""
    fits = [p for p in _KNOWN if p[0] >= w - 1 and p[1] >= h - 1]
    return min(fits, key=lambda p: p[0] * p[1]) if fits else None


def detect_canvas(scenes: list[dict]) -> tuple[int, int]:
    """imc-Canvas eines Kurses aus seinen (bereits gelesenen) Folien bestimmen.

    ``scenes`` ist die Struktur aus :func:`walk_course`. Ausgewertet werden bis
    zu ``_SAMPLE`` echte Folien: zuerst die Thumbnail-Größen (Mehrheit gewinnt),
    sonst die gerundete Rect-Ausdehnung, sonst :data:`DEFAULT_CANVAS`.
    """
    atas = [s['ata'] for sc in scenes for s in sc.get('slides', ())
            if s.get('ata')][:_SAMPLE]
    if not atas:
        return DEFAULT_CANVAS

    sizes = Counter(sz for sz in (_thumb_size(b) for b in atas) if sz)
    if sizes:
        return sizes.most_common(1)[0][0]

    mx = my = 0.0
    for b in atas:
        w, h = _rect_extent(b)
        mx, my = max(mx, w), max(my, h)
    if mx > 0 and my > 0:
        return _round_to_profile(mx, my) or (int(round(mx)), int(round(my)))
    return DEFAULT_CANVAS
