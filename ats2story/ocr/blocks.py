#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR -> positionierte Storyline-Textboxen (mit injizierbarer Geometrie-Transform).

Statt einer einzigen Textbox über den ganzen Bild-Rect liefert
:func:`ocr_textblocks` eine LISTE positionierter Boxen: die Absatz-BBox
(Bild-px, aus der Engine) wird als Anteil am Bild in ein Sub-Rect des
imc-Rects umgerechnet; die Storyline-Transformation übernimmt weiterhin
``build_textbox`` (atsrect-Pfad + ``rect_transform``).
"""
from __future__ import annotations

from collections.abc import Callable

from ..geometry import Rect, fit_rect
from .engine import _median, _ocr_raw, ocr_lang

# Schriftgrößen-Grenzen (pt) für die OCR-Schätzung.
_MIN_PT, _MAX_PT = 9, 40

# Mini-Merge: Absätze mit >= dieser x-Überlappung (bezogen auf die schmalere
# Box) und vertikalem Abstand < _MERGE_GAP_FACTOR * Zeilenhöhe werden zu
# EINER Textbox zusammengefasst (Fließtext-Spalten bleiben zusammen,
# getrennte Beschriftungen bleiben eigene Boxen).
_MERGE_X_OVERLAP = 0.6
_MERGE_GAP_FACTOR = 1.6


def _union(a: tuple | None, b: tuple | None) -> tuple | None:
    """Vereinigung zweier BBoxen (None-tolerant)."""
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _mergeable(group: dict, para: dict) -> bool:
    """Gehört ``para`` in die laufende Gruppe (x-Überlappung + kleiner Abstand)?"""
    gb, pb = group['bbox'], para.get('bbox')
    if gb is None and pb is None:
        return True                     # beide unplatziert -> eine Sammelbox
    if gb is None or pb is None:
        return False
    ref_h = max(int(_median(group['line_hs'])) if group['line_hs'] else 0,
                para.get('line_h') or 0, 1)
    # Vertikaler Abstand in BEIDE Richtungen (Absatz unter ODER über der
    # Gruppe); bei vertikaler Überlappung negativ -> zählt als 0.
    gap = max(pb[1] - gb[3], gb[1] - pb[3])
    if gap >= _MERGE_GAP_FACTOR * ref_h:
        return False
    overlap = min(gb[2], pb[2]) - max(gb[0], pb[0])
    min_w = min(gb[2] - gb[0], pb[2] - pb[0])
    return min_w > 0 and (overlap / min_w) >= _MERGE_X_OVERLAP


def merge_paras(paras: list[dict]) -> list[dict]:
    """Absätze (dict mit bbox/line_h) -> Box-Gruppen (Mini-Merge, reihenfolgetreu).

    Zusammengefasst werden nur AUFEINANDERFOLGENDE Absätze (Lesereihenfolge
    bleibt stabil) mit >= ``_MERGE_X_OVERLAP`` x-Überlappung und vertikalem
    Abstand < ``_MERGE_GAP_FACTOR`` x Zeilenhöhe. Rückgabe je Gruppe:
    ``dict(paras=[...], bbox, line_h)`` — ``line_h`` ist der Median der
    Absatz-Zeilenhöhen der Gruppe (Basis der Schriftgröße PRO Box).
    """
    groups: list[dict] = []
    for p in paras:
        if groups and _mergeable(groups[-1], p):
            g = groups[-1]
            g['paras'].append(p)
            g['bbox'] = _union(g['bbox'], p.get('bbox'))
            if p.get('line_h'):
                g['line_hs'].append(p['line_h'])
        else:
            groups.append(dict(paras=[p], bbox=p.get('bbox'),
                               line_hs=[p['line_h']] if p.get('line_h') else []))
    for g in groups:
        g['line_h'] = int(_median(g['line_hs'])) if g['line_hs'] else 0
        del g['line_hs']
    return groups


def _sub_rect(bbox: tuple, rect: tuple[float, float, float, float],
              img_w: int, img_h: int) -> tuple[float, float, float, float]:
    """Absatz-BBox (Bild-px) -> Sub-Rect (x,y,w,h) im imc-Rect ``rect``."""
    x, y, w, h = rect
    l, t, r, b = bbox
    return (x + (l / img_w) * w, y + (t / img_h) * h,
            ((r - l) / img_w) * w, ((b - t) / img_h) * h)


def ocr_textblocks(
    png_bytes: bytes,
    rect: tuple[float, float, float, float],
    rect_transform: Callable[[float, float, float, float], Rect] = fit_rect,
) -> tuple[list[dict], dict, dict] | None:
    """OCR ein Bild. -> (boxes, base_style, info) wenn es Text ist, sonst None.

    ``boxes`` ist eine Liste positionierter Textboxen:
    ``dict(blocks, rect)`` — ``blocks`` sind die Absatz-Runs der Box (Format
    wie ``build_textbox`` sie erwartet, Schriftgröße PRO Box aus deren
    Zeilenhöhen-Median), ``rect`` das Sub-Rect in imc-Koordinaten (x,y,w,h).
    Die Storyline-Transformation macht weiterhin ``build_textbox``
    (atsrect-Pfad); ``rect_transform`` wird hier nur für die
    Schriftgrößen-Schätzung benutzt und ist injizierbar, damit Tests ohne
    Tesseract und mit eigener Geometrie laufen können.
    """
    if ocr_lang() is None:
        return None
    raw = _ocr_raw(png_bytes)
    if not raw:
        return None
    _l, top, _r, bottom = rect_transform(*rect)
    slide_h = max(1.0, bottom - top)
    img_w = max(1, raw.get('img_w') or 1)
    img_h = max(1, raw['img_h'])

    def _pt(line_h: int) -> int:
        pt = (line_h / img_h) * slide_h * 0.75 if line_h else 16
        return max(_MIN_PT, min(_MAX_PT, round(pt)))

    base_style = dict(fam='Arial', size=str(_pt(raw['med_h'])), color=raw['color'],
                      bold=False, ital=False, under=False)

    paras = raw.get('paras')
    if not paras:
        # Rückwärtskompat: alte raw-Struktur (nur para_runs/para_texts) ->
        # unplatzierte Absätze, unten eine Sammelbox über den ganzen Rect.
        para_runs = raw.get('para_runs') or [[(t, False)] for t in raw['para_texts']]
        paras = [dict(runs=r, bbox=None, line_h=raw['med_h']) for r in para_runs]

    boxes: list[dict] = []
    for grp in merge_paras(paras):
        # Farbe JE BOX (aus dem Bildausschnitt), sonst die Bildfarbe als Notnagel —
        # eine Einheitsfarbe über das ganze Bild verfälscht mehrfarbige Grafiken
        # und macht helle Schrift auf dunklem Grund unsichtbar.
        color = next((p['color'] for p in grp['paras'] if p.get('color')), raw['color'])
        style = dict(base_style, size=str(_pt(grp['line_h'] or raw['med_h'])), color=color)
        blocks = [[(text, dict(style, bold=bool(bold))) for text, bold in p['runs']]
                  for p in grp['paras']]
        brect = (_sub_rect(grp['bbox'], rect, img_w, img_h)
                 if grp['bbox'] is not None else tuple(rect))
        boxes.append(dict(blocks=blocks, rect=brect, bbox_px=grp['bbox']))

    info = dict(conf=raw['conf'], chars=raw['chars'], paras=len(paras), boxes=len(boxes),
                # Anteil Bild-„Tinte" außerhalb der Textkästen und Skalierung der
                # OCR-Koordinaten — der Builder entscheidet damit, ob das Bild als
                # Grafik erhalten bleibt (statt komplett ersetzt zu werden).
                nontext=raw.get('nontext', 0.0), scale=raw.get('scale', 1.0))
    return boxes, base_style, info
