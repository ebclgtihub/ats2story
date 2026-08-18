#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prüft, ob eine neuere Fassung der App veröffentlicht ist.

Bewusst nur ein HINWEIS, kein Selbstaktualisierer: die App lädt nichts
herunter und führt nichts aus. Sie fragt beim Release-Verzeichnis nach der
neuesten Versionsnummer und blendet, falls eine neuere existiert, einen
Verweis auf die Release-Seite ein — der Rest ist eine bewusste Entscheidung
des Benutzers.

Ohne Netz passiert nichts. Ein fehlgeschlagener Aufruf ist kein Fehler,
sondern der Normalfall in einem abgeschotteten Netz; er wird still
verschluckt, damit die App nicht wegen einer Nebensache lärmt.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

#: Öffentliches Verzeichnis der Veröffentlichungen.
REPO = 'ebclgtihub/ats2story'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
PAGE = f'https://github.com/{REPO}/releases/latest'

#: Kurz halten: die Abfrage läuft beim Start und darf niemanden warten lassen.
TIMEOUT = 6

_NUM = re.compile(r'\d+')


def parse_version(text: str | None) -> tuple[int, ...]:
    """``'v1.2.3'`` -> ``(1, 2, 3)``. Unlesbares ergibt ``()``.

    Bewusst nachsichtig: ein Tag darf ein ``v`` tragen, Vorabkennungen wie
    ``-beta`` werden abgeschnitten. Was gar keine Zahl enthält, gilt als
    unbekannt und löst deshalb keinen Hinweis aus.
    """
    if not text:
        return ()
    head = str(text).strip().lstrip('vV').split('-')[0].split('+')[0]
    return tuple(int(n) for n in _NUM.findall(head)[:4])


def is_newer(latest: str | None, current: str | None) -> bool:
    """Ist ``latest`` echt neuer als ``current``?

    Bei unlesbaren Angaben lieber KEIN Hinweis — ein falscher Alarm ist
    lästiger als ein ausgelassener.
    """
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest_release(timeout: float = TIMEOUT, url: str = API) -> dict | None:
    """Neueste veröffentlichte Fassung -> ``{'version', 'url', 'name'}``.

    ``None``, wenn nichts zu erfahren ist (kein Netz, Sperre, unerwartete
    Antwort). Der Aufrufer soll daraus nichts weiter folgern.
    """
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        # GitHub verlangt eine Kennung; ohne sie kommt 403 zurück.
        'User-Agent': f'ats2story-updatecheck ({REPO})',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, 'status', 200) != 200:
                return None
            data = json.loads(resp.read(200_000).decode('utf-8', 'replace'))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get('tag_name') or data.get('name')
    if not parse_version(tag):
        return None
    return dict(version=str(tag).lstrip('vV'),
                url=str(data.get('html_url') or PAGE),
                name=str(data.get('name') or tag))


def check(current: str, timeout: float = TIMEOUT, url: str = API) -> dict | None:
    """``{'version', 'url'}``, wenn es etwas Neueres gibt — sonst ``None``."""
    rel = latest_release(timeout=timeout, url=url)
    if not rel or not is_newer(rel['version'], current):
        return None
    return rel
