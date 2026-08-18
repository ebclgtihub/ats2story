#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für das ocr-Paket (ohne echtes Tesseract)."""
from __future__ import annotations

import pytest

from ats2story.ocr import blocks as ocr_blocks
from ats2story.ocr import config
from ats2story.ocr import engine
from ats2story.ocr.engine import _append_run, _normalize_runs


def test_config_state_is_read_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine liest TESSERACT_CMD zur Laufzeit aus config (nicht beim Import)."""
    monkeypatch.setattr(config, 'OCR_TESSDATA', '/custom/tessdata')
    env = engine._ocr_env()
    assert env.get('TESSDATA_PREFIX') == '/custom/tessdata'


def test_ocr_lang_caches_and_respects_pref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, '_OCR_LANG_CACHE', None)
    monkeypatch.setattr(config, 'OCR_LANG_PREF', 'deu')

    class FakeRun:
        stdout = 'List of available languages:\ndeu\neng\n'

    monkeypatch.setattr(engine.subprocess, 'run', lambda *a, **k: FakeRun())
    assert engine.ocr_lang() == 'deu'
    # zweiter Aufruf nutzt Cache
    assert config._OCR_LANG_CACHE == 'deu'


def test_ocr_lang_falls_back_to_eng(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, '_OCR_LANG_CACHE', None)
    monkeypatch.setattr(config, 'OCR_LANG_PREF', 'deu')

    class FakeRun:
        stdout = 'List of available languages:\neng\n'

    monkeypatch.setattr(engine.subprocess, 'run', lambda *a, **k: FakeRun())
    assert engine.ocr_lang() == 'eng'


def test_ocr_lang_none_when_no_langs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, '_OCR_LANG_CACHE', None)

    def boom(*a, **k):
        raise FileNotFoundError('no tesseract')

    monkeypatch.setattr(engine.subprocess, 'run', boom)
    assert engine.ocr_lang() is None


def test_append_run_merges_same_format() -> None:
    runs: list[tuple[str, bool]] = []
    _append_run(runs, 'Hallo', False)
    _append_run(runs, ' Welt', False)
    assert runs == [('Hallo Welt', False)]


def test_append_run_splits_on_format_change() -> None:
    runs: list[tuple[str, bool]] = []
    _append_run(runs, 'normal', False)
    _append_run(runs, ' fett', True)
    assert runs == [('normal', False), (' fett', True)]


def test_normalize_runs_trims_leading_space() -> None:
    out = _normalize_runs([(' abc', False), ('', True)])
    assert out == [('abc', False)]


def test_ocr_textblocks_injectable_transform(monkeypatch: pytest.MonkeyPatch) -> None:
    """rect_transform injizierbar -> testbar ohne Tesseract."""
    monkeypatch.setattr(ocr_blocks, 'ocr_lang', lambda: 'deu')
    monkeypatch.setattr(ocr_blocks, '_ocr_raw', lambda png: dict(
        paras=[
            dict(runs=[('Titel ', True), ('normal', False)], text='Titel normal',
                 bbox=(0, 0, 400, 40), line_h=20),
            dict(runs=[('zweiter Absatz', False)], text='zweiter Absatz',
                 bbox=(0, 200, 400, 240), line_h=20),
        ],
        para_runs=[[('Titel ', True), ('normal', False)], [('zweiter Absatz', False)]],
        para_texts=['Titel normal', 'zweiter Absatz'],
        med_h=20, img_w=400, img_h=400, conf=88, chars=25, color='#112233'))

    calls = []

    def fake_transform(x, y, w, h):
        calls.append((x, y, w, h))
        return (0.0, 0.0, 1280.0, 720.0)

    result = ocr_blocks.ocr_textblocks(b'png', (10, 20, 100, 50), rect_transform=fake_transform)
    assert result is not None
    boxes, style, info = result
    assert calls == [(10, 20, 100, 50)]          # transform wurde injiziert genutzt
    assert info['paras'] == 2                     # zwei Absätze erhalten
    # Vertikaler Abstand (160 px) >> 1,6*Zeilenhöhe -> KEIN Merge, zwei Boxen.
    assert info['boxes'] == 2
    assert style['color'] == '#112233'
    # Sub-Rects: BBox-Anteil am 400x400-Bild -> Anteil am imc-Rect (10,20,100,50).
    assert boxes[0]['rect'] == pytest.approx((10.0, 20.0, 100.0, 5.0))
    assert boxes[1]['rect'] == pytest.approx((10.0, 45.0, 100.0, 5.0))
    # Fett-Run erhalten:
    first_para = boxes[0]['blocks'][0]
    assert first_para[0][0] == 'Titel '
    assert first_para[0][1]['bold'] is True
    assert first_para[1][1]['bold'] is False


def test_ocr_textblocks_none_without_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_blocks, 'ocr_lang', lambda: None)
    assert ocr_blocks.ocr_textblocks(b'png', (0, 0, 10, 10)) is None


# ---- Windows: keine aufblitzenden Konsolenfenster ---------------------------

def test_no_window_flag_is_zero_off_windows() -> None:
    """Auf macOS/Linux gibt es CREATE_NO_WINDOW nicht -> 0 (= keine Wirkung)."""
    import subprocess as sp
    expected = getattr(sp, 'CREATE_NO_WINDOW', 0)
    assert engine._no_window() == expected


def test_no_window_flag_is_used_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unter Windows muss das Flag gesetzt sein — die App ist windowed, sonst
    öffnet JEDER Tesseract-Aufruf kurz ein schwarzes Konsolenfenster."""
    monkeypatch.setattr(engine.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    assert engine._no_window() == 0x08000000


def test_tesseract_call_passes_creationflags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beide Subprozess-Aufrufe (OCR-Lauf und --list-langs) reichen das Flag durch."""
    from PIL import Image

    seen: list[dict] = []

    class FakeRun:
        stdout = b'level\tpage_num\n'

    def fake_run(cmd, **kw):
        seen.append(kw)
        return FakeRun()

    monkeypatch.setattr(engine.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(engine.subprocess, 'run', fake_run)
    engine._run_tesseract(Image.new('L', (4, 4), 255), 'deu', 3)
    assert seen and seen[0].get('creationflags') == 0x08000000

    seen.clear()
    monkeypatch.setattr(config, '_OCR_LANG_CACHE', None)

    class FakeText:
        stdout = 'List of available languages:\ndeu\n'

    monkeypatch.setattr(engine.subprocess, 'run', lambda cmd, **kw: (seen.append(kw), FakeText())[1])
    engine.ocr_lang()
    assert seen and seen[0].get('creationflags') == 0x08000000
