#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests für das Absatz-Clustering/Merge in ocr.blocks (rein synthetisch,
kein Tesseract — merge_paras/_sub_rect sind pure Funktionen)."""
from __future__ import annotations

import pytest

from ats2story.ocr import blocks as ocr_blocks
from ats2story.ocr.blocks import _sub_rect, merge_paras


def _para(text: str, bbox: tuple | None, line_h: int = 20) -> dict:
    return dict(text=text, runs=[(text, False)], bbox=bbox, line_h=line_h)


def test_merge_stacked_paragraphs_into_one_box() -> None:
    """Direkt übereinander (Abstand < 1,6x Zeilenhöhe, x-Überlappung) -> 1 Box."""
    paras = [
        _para('Zeile eins', (10, 10, 300, 30)),
        _para('Zeile zwei', (12, 40, 290, 60)),   # Abstand 10 < 32
    ]
    groups = merge_paras(paras)
    assert len(groups) == 1
    assert len(groups[0]['paras']) == 2
    assert groups[0]['bbox'] == (10, 10, 300, 60)  # BBox-Union
    assert groups[0]['line_h'] == 20


def test_no_merge_when_vertical_gap_too_large() -> None:
    """Abstand >= 1,6x Zeilenhöhe -> getrennte Boxen (z.B. Titel vs. Fußzeile)."""
    paras = [
        _para('Titel', (10, 10, 300, 30)),
        _para('Fusszeile', (10, 200, 300, 220)),   # Abstand 170 >> 32
    ]
    groups = merge_paras(paras)
    assert len(groups) == 2


def test_no_merge_for_side_by_side_columns() -> None:
    """Nebeneinanderliegende Spalten (vertikal überlappend, aber < 60%
    x-Überlappung) bleiben getrennte Boxen."""
    paras = [
        _para('linke Spalte', (0, 10, 100, 30)),
        _para('rechte Spalte', (200, 10, 300, 30)),   # keine x-Überlappung
    ]
    groups = merge_paras(paras)
    assert len(groups) == 2


def test_merge_is_order_stable_and_consecutive_only() -> None:
    """Nur AUFEINANDERFOLGENDE Absätze verschmelzen — ein dazwischenliegender
    entfernter Absatz trennt auch räumlich nahe Nachbarn."""
    paras = [
        _para('a', (10, 10, 300, 30)),
        _para('weit weg', (10, 500, 300, 520)),
        _para('b', (10, 40, 300, 60)),   # nah an 'a', aber nicht benachbart
    ]
    groups = merge_paras(paras)
    assert len(groups) == 3
    assert [g['paras'][0]['text'] for g in groups] == ['a', 'weit weg', 'b']


def test_merge_line_h_median_per_box() -> None:
    paras = [
        _para('gross', (10, 10, 300, 50), line_h=40),
        _para('auch gross', (10, 55, 300, 95), line_h=36),
    ]
    groups = merge_paras(paras)
    assert len(groups) == 1
    assert groups[0]['line_h'] == 40   # Median von [40, 36]


def test_sub_rect_maps_bbox_fraction_into_imc_rect() -> None:
    # BBox = rechtes unteres Viertel eines 200x100-Bildes.
    rect = (50.0, 60.0, 400.0, 200.0)   # imc (x,y,w,h)
    sub = _sub_rect((100, 50, 200, 100), rect, 200, 100)
    assert sub == pytest.approx((250.0, 160.0, 200.0, 100.0))


def test_ocr_textblocks_per_box_font_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schriftgröße PRO Box aus deren Zeilenhöhen-Median (Titel > Fließtext)."""
    monkeypatch.setattr(ocr_blocks, 'ocr_lang', lambda: 'deu')
    monkeypatch.setattr(ocr_blocks, '_ocr_raw', lambda png: dict(
        paras=[
            dict(runs=[('Titel', True)], text='Titel', bbox=(0, 0, 400, 48), line_h=40),
            dict(runs=[('kleiner Fliesstext', False)], text='kleiner Fliesstext',
                 bbox=(0, 300, 400, 320), line_h=16),
        ],
        para_runs=[[('Titel', True)], [('kleiner Fliesstext', False)]],
        para_texts=['Titel', 'kleiner Fliesstext'],
        med_h=16, img_w=400, img_h=400, conf=90, chars=24, color='#000000'))

    result = ocr_blocks.ocr_textblocks(
        b'png', (0, 0, 1024, 748), rect_transform=lambda x, y, w, h: (0, 0, 1024, 748))
    assert result is not None
    boxes, _style, info = result
    assert info['boxes'] == 2
    size_title = int(boxes[0]['blocks'][0][0][1]['size'])
    size_body = int(boxes[1]['blocks'][0][0][1]['size'])
    assert size_title > size_body


def test_ocr_textblocks_compat_raw_without_paras(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alte raw-Struktur (ohne paras/bbox) -> EINE Sammelbox über den ganzen Rect."""
    monkeypatch.setattr(ocr_blocks, 'ocr_lang', lambda: 'deu')
    monkeypatch.setattr(ocr_blocks, '_ocr_raw', lambda png: dict(
        para_runs=[[('alt', False)], [('kompatibel', False)]],
        para_texts=['alt', 'kompatibel'],
        med_h=20, img_h=400, conf=80, chars=14, color='#333333'))
    result = ocr_blocks.ocr_textblocks(b'png', (5, 6, 70, 80))
    assert result is not None
    boxes, _style, info = result
    assert info['boxes'] == 1
    assert boxes[0]['rect'] == (5, 6, 70, 80)
    assert len(boxes[0]['blocks']) == 2
