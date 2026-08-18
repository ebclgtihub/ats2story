#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grafikerhalt bei OCR: Text im Bild ausstempeln statt das Bild zu verwerfen.

Bisher ersetzte der Konverter ein Bild, in dem OCR Text fand, KOMPLETT durch
Textboxen. Bei reinen Textgrafiken ist das richtig — bei Diagrammen,
Screenshots oder beschrifteten Abbildungen ging damit die gesamte Grafik
verloren.

Hier entscheidet :func:`nontext_ink_ratio`, wie viel „Tinte" (Nicht-Hintergrund)
AUSSERHALB der erkannten Textkästen liegt. Ist das nennenswert, bleibt das Bild
erhalten und :func:`erase_text_regions` überstempelt nur die Textkästen mit der
lokalen Hintergrundfarbe — die Textboxen liegen dann darüber, alles bleibt
bearbeitbar und die Grafik bleibt sichtbar.
"""
from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw, ImageFilter

_log = logging.getLogger(__name__)

#: Ab diesem Anteil Nicht-Text-Tinte gilt ein Bild als „enthält auch Grafik".
NONTEXT_KEEP_RATIO = 0.15

#: Luminanz-Abstand vom Hintergrund, ab dem ein Pixel als „Tinte" zählt.
_INK_DELTA = 45

#: Rand (px), um den Textkästen beim Ausstempeln vergrößert werden
#: (Antialiasing-Säume der Glyphen).
_PAD = 2


def _bg_luminance(gray: Image.Image) -> int:
    """Häufigste Luminanz (16er-Klassen) = Hintergrund des Bildes."""
    hist = gray.histogram()
    buckets = [sum(hist[i * 16:(i + 1) * 16]) for i in range(16)]
    return buckets.index(max(buckets)) * 16 + 8


def nontext_ink_ratio(gray: Image.Image, boxes_px: list[tuple]) -> float:
    """Anteil der Tinte-Pixel, der AUSSERHALB der Textkästen liegt (0..1).

    ``gray`` ist das auf Weiß geflachte Graustufenbild (wie es die OCR-Engine
    benutzt), ``boxes_px`` sind die Text-BBoxen ``(l, t, r, b)`` in denselben
    Bildkoordinaten. 0.0 = alle Tinte steckt im Text (reine Textgrafik).
    """
    bg = _bg_luminance(gray)
    lo, hi = bg - _INK_DELTA, bg + _INK_DELTA
    ink = gray.point(lambda v: 255 if (v < lo or v > hi) else 0, mode='L')
    total = sum(i * c for i, c in enumerate(ink.histogram())) / 255
    if total <= 0:
        return 0.0
    covered = Image.new('L', gray.size, 0)
    d = ImageDraw.Draw(covered)
    for box in boxes_px:
        if not box:
            continue
        l, t, r, b = (int(v) for v in box)
        d.rectangle((l - _PAD, t - _PAD, r + _PAD, b + _PAD), fill=255)
    from PIL import ImageChops
    inside = ImageChops.multiply(ink, covered)
    inside_n = sum(i * c for i, c in enumerate(inside.histogram())) / 255
    return max(0.0, min(1.0, (total - inside_n) / total))


def erase_text_regions(png_bytes: bytes, boxes_px: list[tuple],
                       scale: float = 1.0) -> bytes | None:
    """Textkästen im Bild mit der lokalen Hintergrundfarbe füllen.

    ``scale`` ist der Faktor, mit dem die OCR-Koordinaten gegenüber dem
    Originalbild skaliert sind (die Engine skaliert kleine Schrift vor der
    Erkennung hoch) — die Kästen werden damit zurückgerechnet.

    Die Füllfarbe wird je Kasten aus einem Rahmen um den Kasten gemittelt
    (nicht global), damit farbige Flächen erhalten bleiben. Rückgabe: PNG-Bytes
    oder ``None``, wenn nichts ersetzt werden konnte.
    """
    try:
        im = Image.open(io.BytesIO(png_bytes))
        im = im.convert('RGBA')
    except Exception as exc:
        _log.debug('erase_text_regions: Bild nicht lesbar: %s', exc, exc_info=True)
        return None

    drew = 0
    d = ImageDraw.Draw(im)
    for box in boxes_px:
        if not box:
            continue
        l, t, r, b = (int(round(v / scale)) for v in box)
        l, t = max(0, l - _PAD), max(0, t - _PAD)
        r, b = min(im.width, r + _PAD), min(im.height, b + _PAD)
        if r - l < 2 or b - t < 2:
            continue
        d.rectangle((l, t, r - 1, b - 1), fill=_surround_color(im, (l, t, r, b)))
        drew += 1
    if not drew:
        return None
    # Weiche Kanten: die gestempelten Flächen leicht glätten, damit harte
    # Rechteckkanten auf Verläufen nicht auffallen.
    try:
        im = im.filter(ImageFilter.SMOOTH)
    except Exception:
        pass
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _surround_color(im: Image.Image, box: tuple[int, int, int, int]) -> tuple:
    """Mittlere Farbe eines schmalen Rahmens UM ``box`` (lokaler Hintergrund)."""
    l, t, r, b = box
    pad = 4
    outer = (max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad))
    try:
        ring = im.crop(outer).convert('RGBA')
    except Exception:
        return (255, 255, 255, 255)
    px = ring.load()
    acc = [0, 0, 0, 0]
    n = 0
    for y in range(ring.height):
        for x in range(ring.width):
            on_edge = x < pad or y < pad or x >= ring.width - pad or y >= ring.height - pad
            if not on_edge:
                continue
            p = px[x, y]
            for i in range(4):
                acc[i] += p[i]
            n += 1
    if not n:
        return (255, 255, 255, 255)
    return tuple(v // n for v in acc)
