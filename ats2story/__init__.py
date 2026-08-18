#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ats2story — Konverter imc Content Studio (.ats) -> Articulate Storyline (.story).

KOMPATIBILITÄTS-SHIM. Die eigentliche Logik liegt in den Submodulen
(ats_reader/, media/, ocr/, richtext/, story_writer/, converter, cli). Dieses
Paket re-exportiert die bisherige öffentliche API, damit bestehende Importe
(`import ats2story; ats2story.convert_ats(...)`) unverändert funktionieren.

WICHTIG — veränderlicher OCR-State (TESSERACT_CMD/OCR_TESSDATA/OCR_LANG_PREF/
_OCR_LANG_CACHE): Diese Namen werden auf dieses Modul GESCHRIEBEN (z.B. von der
Desktop-App). Ein simpler Re-Export würde solche Zuweisungen an die OCR-Engine
NICHT weiterreichen. Deshalb ersetzt dieses Modul seine Klasse durch einen
Proxy, der genau diese Namen transparent auf ``ats2story.ocr.config`` umleitet
(lesen UND schreiben). Die Engine liest config.* zur Laufzeit -> ein
``ats2story.TESSERACT_CMD = ...`` wirkt sofort.
"""
from __future__ import annotations

#: Die eine Quelle der Versionsnummer. pyproject.toml liest sie hier aus,
#: die App zeigt sie an und vergleicht sie mit dem letzten Release.
__version__ = '1.0.4'

import sys as _sys
from types import ModuleType as _ModuleType

from .ats_reader import (  # noqa: F401
    NS,
    cp,
    rect_of,
    slide_content,
    detect_canvas,
    thumbnail,
    walk_course,
)
from .converter import (  # noqa: F401
    DEF_ATS,
    DEF_TPL,
    convert_ats,
)
from .geometry import (  # noqa: F401
    ATS_H,
    ATS_W,
    SLD_H,
    SLD_W,
    extract_element,
    fill_rect,
    find_first,
    fit_rect,
)
from .guid import (  # noqa: F401
    GUID_RE,
    ZERO,
    b62,
    guid_b62,
    media_filename,
    newg,
    reguid,
    relid,
    relid_from_guid,
)
from .media import (  # noqa: F401
    MediaPool,
    mp3_duration_ms,
    mp3_info,
    wav_to_mp3,
)
from .ocr import config as _ocr_config  # noqa: F401
from .ocr import ocr_lang, ocr_textblocks  # noqa: F401
from .ocr.engine import (  # noqa: F401
    _flatten_gray,
    _ocr_env,
    _ocr_raw,
    _text_color,
)
from .richtext import (  # noqa: F401
    fmt_document,
    inline_runs,
    norm_color,
    parse_richtext,
)
from .story_writer import (  # noqa: F401
    MIN_DUR,
    Builder,
    Template,
    add_media_pool,
    build_summary,
    clean_backgrounds,
    patch_story_xml,
    strip_quiz,
    write_story_package,
)

# -- Proxy für veränderlichen OCR-State --------------------------------------
#: Namen, deren Lesen/Schreiben transparent auf ats2story.ocr.config geht.
#: OCR_MIN_CONF/OCR_MIN_CHARS sind hier bewusst MIT drin (statt Einmal-Kopie),
#: damit Lesen UND Schreiben konsistent auf ocr.config wirken. Diese Namen
#: dürfen NICHT zusätzlich im Modul-__dict__ stehen — sonst greift __getattr__
#: (das nur bei fehlendem Attribut feuert) für Lesezugriffe nicht.
_PROXIED = frozenset({
    'TESSERACT_CMD', 'OCR_TESSDATA', 'OCR_LANG_PREF', '_OCR_LANG_CACHE', '_ocr_errors',
    'OCR_MIN_CONF', 'OCR_MIN_CHARS',
})


class _Ats2StoryModule(_ModuleType):
    """Modul-Proxy: leitet OCR-State-Namen auf ats2story.ocr.config um."""

    def __getattr__(self, name: str):
        if name in _PROXIED:
            return getattr(_ocr_config, name)
        raise AttributeError(f'module {self.__name__!r} has no attribute {name!r}')

    def __setattr__(self, name: str, value) -> None:
        if name in _PROXIED:
            setattr(_ocr_config, name, value)
        else:
            super().__setattr__(name, value)


# Klasse des aktuellen Moduls umhängen — bewahrt alle bereits gesetzten
# Attribute im __dict__, fängt aber künftige Lese-/Schreibzugriffe auf
# OCR-State-Namen ab.
_sys.modules[__name__].__class__ = _Ats2StoryModule
