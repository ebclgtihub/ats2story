#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thumbnail-Extraktion aus einer .ata-Folie."""
from __future__ import annotations

import io
import zipfile

from ..security import safe_zip_read


def thumbnail(ata_bytes: bytes) -> bytes | None:
    """Erstes ``*thumbnail*.png`` aus der .ata-ZIP — oder ``None``."""
    try:
        with zipfile.ZipFile(io.BytesIO(ata_bytes)) as ata:
            for n in ata.namelist():
                if 'thumbnail' in n.lower() and n.lower().endswith('.png'):
                    try:
                        return safe_zip_read(ata, n)
                    except ValueError:
                        continue  # zip-slip or bomb — skip
    except Exception:
        pass
    return None
