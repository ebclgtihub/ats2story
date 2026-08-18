#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests für Fett-Heuristik + Absatz-Erhalt durch die OCR->fmtText-Kette.

Tesseract wird durch einen TSV-liefernden Fake ersetzt; die Bild-Dekodierung
(_flatten_gray) und die Stroke-Dichte (_word_bold) werden gemockt, sodass der
Pfad ohne echte Engine/Bilder läuft.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from ats2story.ocr import blocks as ocr_blocks
from ats2story.ocr import config
from ats2story.ocr import engine
from ats2story.richtext import fmt_document


def _fake_png() -> bytes:
    buf = io.BytesIO()
    Image.new('RGBA', (200, 100), (255, 255, 255, 255)).save(buf, 'PNG')
    return buf.getvalue()


# TSV: par 1 line 1 = "Titel" (fett), line 2 = "fliesstext normal";
#      par 2 line 1 = "Zweiter Absatz"
_TSV = (
    'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    '5\t1\t1\t1\t1\t1\t10\t10\t80\t30\t95\tTitel\n'
    '5\t1\t1\t1\t2\t1\t10\t50\t60\t20\t92\tfliesstext\n'
    '5\t1\t1\t1\t2\t2\t80\t50\t40\t20\t92\tnormal\n'
    '5\t1\t1\t2\t1\t1\t10\t90\t70\t20\t90\tZweiter\n'
    '5\t1\t1\t2\t1\t2\t90\t90\t60\t20\t90\tAbsatz\n'
)


class _FakeRun:
    def __init__(self):
        self.stdout = _TSV.encode('utf-8')


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch):
    # Cache leeren, Sprache vorhanden, Tesseract-Aufruf faken.
    engine._OCR_RAW_CACHE.clear()
    monkeypatch.setattr(config, '_OCR_LANG_CACHE', 'deu')
    monkeypatch.setattr(engine.subprocess, 'run', lambda *a, **k: _FakeRun())
    monkeypatch.setattr(engine, '_text_color', lambda im: '#101010')
    # Graustufen-Flatten umgehen (gibt RGBA + dummy gray zurück).
    gray = Image.new('L', (200, 100), 255)
    rgba = Image.new('RGBA', (200, 100), (255, 255, 255, 255))
    monkeypatch.setattr(engine, '_flatten_gray', lambda b: (rgba, gray))
    # _word_bold: "Titel" (top=10) fett, Rest normal — nach top unterscheiden.
    monkeypatch.setattr(engine, '_word_bold',
                        lambda g, left, top, w, h: 0.9 if top < 40 else 0.1)


def test_ocr_raw_marks_bold_word() -> None:
    raw = engine._ocr_raw(_fake_png())
    assert raw is not None
    # zwei Absätze erhalten
    assert len(raw['para_texts']) == 2
    assert raw['para_texts'][0].startswith('Titel')
    assert raw['para_texts'][1] == 'Zweiter Absatz'
    # erster Absatz hat einen fetten Run ("Titel") und einen normalen Rest
    runs = raw['para_runs'][0]
    bold_flags = {txt.strip(): bold for txt, bold in runs}
    assert bold_flags.get('Titel') is True
    # zweiter Absatz komplett normal
    assert all(not bold for _txt, bold in raw['para_runs'][1])


def test_bold_flows_into_fmt_document() -> None:
    blocks_result = ocr_blocks.ocr_textblocks(_fake_png(), (0, 0, 1024, 748))
    assert blocks_result is not None
    boxes, _style, info = blocks_result
    assert info['paras'] == 2          # Absatz-Erhalt
    # Die zwei Absätze liegen direkt übereinander (Abstand < 1,6x Zeilenhöhe,
    # volle x-Überlappung) -> Mini-Merge zu EINER Box mit zwei Blöcken.
    assert info['boxes'] == 1
    doc = fmt_document(boxes[0]['blocks'], 'left')
    # Mindestens ein fetter Span (Titel) und mindestens ein normaler.
    assert 'FontIsBold="True"' in doc
    assert 'FontIsBold="False"' in doc
    assert 'Titel' in doc
    assert 'Zweiter' in doc
