#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUID- und ID-Helfer (Storyline-Konventionen).

Storyline leitet Kurz-IDs und Mediendateinamen deterministisch aus GUIDs ab —
diese Ableitungen MÜSSEN exakt stimmen, sonst meldet Storyline "unreadable
asset" / "corrupt". Siehe memory/story-format.md.
"""
from __future__ import annotations

import re
import uuid

#: All-Zero-GUID (Platzhalter / "keine Referenz").
ZERO: str = '00000000-0000-0000-0000-000000000000'

#: Erkennt eine GUID im 8-4-4-4-12-Hex-Format.
GUID_RE: re.Pattern[str] = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)

_B62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'


def newg() -> str:
    """Frische zufällige GUID als String."""
    return str(uuid.uuid4())


def b62(n: int) -> str:
    """base62-Kodierung einer nicht-negativen Ganzzahl."""
    if n == 0:
        return _B62[0]
    s = ''
    while n:
        n, r = divmod(n, 62)
        s = _B62[r] + s
    return s


def guid_b62(guid: str) -> str:
    """base62(int_le(GUID.bytes_le[:8])) — Storylines GUID->Kurz-ID-Ableitung."""
    return b62(int.from_bytes(uuid.UUID(guid).bytes_le[:8], 'little'))


def media_filename(guid: str, ext: str) -> str:
    """Storyline-Dateiname aus GUID:  R + base62(int_le(GUID.bytes_le[:8])) + .ext"""
    return f'R{guid_b62(guid)}.{ext}'


def relid_from_guid(guid: str) -> str:
    """Slide/Szene-Rel-Id = R + base62(GUID) (Storyline-Konvention, NICHT zufällig!)."""
    return 'R' + guid_b62(guid)


def relid() -> str:
    """Zufällige Rel-Id (für Medien-Relationships ohne feste GUID-Bindung)."""
    return 'R' + uuid.uuid4().hex[:16]


def reguid(frag: str, preserve: frozenset[str] | set[str]) -> str:
    """Alle GUIDs in ``frag`` durch frische ersetzen, außer ZERO und in ``preserve``.

    Konsistent: gleiche Quell-GUID -> gleiche neue GUID innerhalb des Fragments.
    """
    mapping: dict[str, str] = {}

    def repl(m: re.Match[str]) -> str:
        g = m.group(0).lower()
        if g == ZERO or g in preserve:
            return m.group(0)
        return mapping.setdefault(g, newg())

    return GUID_RE.sub(repl, frag)
