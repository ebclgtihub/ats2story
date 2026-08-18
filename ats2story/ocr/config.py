#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR-Konfiguration und veränderlicher Modul-State.

WICHTIG (Shim/State-Thema): Diese Werte sind veränderlich und werden zur
LAUFZEIT von :mod:`ats2story.ocr.engine` gelesen — NICHT beim Import kopiert.
So wirkt ein ``config.TESSERACT_CMD = ...`` sofort auf die Engine.

``converter_app/app.py`` schreibt direkt auf dieses Modul
(``from ats2story.ocr import config``; ``config.TESSERACT_CMD = ...``), weil
eine Zuweisung an das Kompat-Shim-Modul (``ats2story``) die Engine NICHT
erreichen würde.
"""
from __future__ import annotations

import os

#: Bevorzugte OCR-Sprache (Tesseract-Code).
OCR_LANG_PREF: str = 'deu'

#: Optionales eigenes tessdata-Verzeichnis (mit z.B. deu.traineddata).
OCR_TESSDATA: str | None = os.environ.get('ATS_TESSDATA')

#: Tesseract-Binary; gebündeltes Binary (PyInstaller) überschreibt das.
TESSERACT_CMD: str = os.environ.get('ATS_TESSERACT', 'tesseract')

#: Mittlere Wort-Konfidenz, ab der ein Bild als Text gilt.
OCR_MIN_CONF: int = 70

#: Mindest-Textlänge, damit ein Bild als Text gilt.
OCR_MIN_CHARS: int = 6

#: Cache: ``None`` = noch nicht ermittelt; ``''`` = keine Sprache; sonst Code.
_OCR_LANG_CACHE: str | None = None

#: Zähler für OCR-subprocess/Decode-Fehler (distinct von Nicht-Text-Bildern).
_ocr_errors: int = 0


def reset_lang_cache() -> None:
    """Sprach-Cache invalidieren (nach Änderung von OCR_LANG_PREF/CMD/TESSDATA)."""
    global _OCR_LANG_CACHE
    _OCR_LANG_CACHE = None
