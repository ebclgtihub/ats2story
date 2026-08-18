#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bild-Dekodierung + Re-Encode (non-interlaced/baseline) mit Bomb-Guard."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFile

from ..security import IMG_PIXEL_MAX

# imc-PNGs haben teils abgeschnittenes IEND/CRC -> tolerant dekodieren.
ImageFile.LOAD_TRUNCATED_IMAGES = True


@dataclass(frozen=True)
class EncodedImage:
    """Re-encodiertes Bild + Metadaten."""

    data: bytes
    ext: str      # 'png' | 'jpg'
    mtype: str    # 'Png' | 'Jpeg'
    width: int
    height: int


def apply_opacity(raw: bytes, opacity: float) -> bytes:
    """Deckkraft (imc ``opacity``, 0..100) in den Alphakanal des Bildes rechnen.

    Storyline kennt zwar ein ``trans``-Attribut am ``picFormat``, dessen Skala
    ist in allen vorliegenden Referenzdateien aber ausschließlich ``0`` — also
    unbelegt. Statt zu raten wird die Deckkraft in das PNG selbst gerechnet:
    das Ergebnis stimmt garantiert und das Bild bleibt ein normales,
    austauschbares Bild-Shape. Bei ``opacity >= 100`` bleibt ``raw`` unverändert.
    """
    if opacity is None or opacity >= 100 or opacity < 0:
        return raw
    try:
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > IMG_PIXEL_MAX:
            return raw
        im = im.convert('RGBA')
        alpha = im.getchannel('A').point(lambda v: int(v * opacity / 100))
        im.putalpha(alpha)
        buf = io.BytesIO()
        im.save(buf, 'PNG', interlace=False, optimize=False)
        return buf.getvalue()
    except Exception:
        return raw


def reencode_image(raw: bytes) -> EncodedImage | None:
    """Dekodiert ``raw`` und re-encodiert non-interlaced (PNG) bzw. baseline (JPG).

    Gibt ``None`` zurück, wenn das Bild nicht dekodierbar ist (z.B. EMF/SVG/
    korrupt) oder den Pixel-Cap (decompression-bomb) überschreitet.
    """
    try:
        im = Image.open(io.BytesIO(raw))
        # decompression-bomb guard before .load()
        if im.width * im.height > IMG_PIXEL_MAX:
            return None
        im.load()
    except Exception:
        return None
    buf = io.BytesIO()
    if (im.format or '').upper() in ('JPEG', 'JPG') and im.mode != 'P':
        im = im.convert('RGB')
        im.save(buf, 'JPEG', quality=88, optimize=True, progressive=False)
        ext, mtype = 'jpg', 'Jpeg'
    else:
        im = im.convert('RGBA')
        im.save(buf, 'PNG', interlace=False, optimize=False)
        ext, mtype = 'png', 'Png'
    return EncodedImage(data=buf.getvalue(), ext=ext, mtype=mtype,
                        width=im.width, height=im.height)
