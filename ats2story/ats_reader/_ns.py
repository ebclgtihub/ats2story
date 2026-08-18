#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemeinsame XML-Namespace-Konstante und ET-Import für den .ats-Reader.

imc Content Studio nutzt den Authoring-Namespace. Wir bevorzugen defusedxml
für nicht vertrauenswürdiges XML (Schutz gegen XXE/Billion-Laughs).
"""
from __future__ import annotations

import warnings

try:  # bevorzugt defusedxml für untrusted XML
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover - Fallback wenn defusedxml fehlt
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

    warnings.warn(
        'defusedxml nicht installiert — stdlib-XML ohne XXE-Schutz',
        RuntimeWarning,
        stacklevel=2,
    )

#: imc-Authoring-Namespace (als ElementTree-Prefix ``{...}``).
NS: str = '{http://im-c.de/xml/authoring/1.0}'

__all__ = ['ET', 'NS']
