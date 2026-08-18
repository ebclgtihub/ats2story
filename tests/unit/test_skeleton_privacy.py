#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Das eingebaute Gerüst darf KEINE Kundendaten enthalten.

``ats2story/assets/skeleton.story`` ist das einzige Kurs-Binärformat, das
bewusst versioniert wird (``.gitignore`` schließt sonst alle ``.ats``/``.story``
aus). Es stammt aus einer echten Storyline-Datei — und trug ursprünglich
Kundenlogos, Figuren, Fotos, zwei MP3s, ein PDF, 53 Folien-Vorschaubilder, ein
1,7-MB-Kursvorschaubild, Kurstexte, Windows-Benutzerkonten und absolute
OneDrive-Pfade mit sich. Aus der Git-Historie ließe sich das im Nachhinein nicht
mehr einfach entfernen.

Diese Tests halten den bereinigten Zustand fest. Wird das Gerüst neu erzeugt,
muss es durch ``scripts/sanitize_skeleton.py`` gelaufen sein.
"""
from __future__ import annotations

import os
import re
import zipfile

import pytest

import ats2story

SKELETON = ats2story.DEF_TPL

#: Größen-Deckel: das bereinigte Gerüst liegt bei ~1 MB. Rutscht es deutlich
#: darüber, stecken vermutlich wieder Medien oder base64-Vorschauen darin.
MAX_BYTES = 2 * 1024 * 1024


@pytest.fixture(scope='module')
def parts() -> dict[str, bytes]:
    if not os.path.isfile(SKELETON):
        pytest.skip(f'Gerüst fehlt: {SKELETON}')
    with zipfile.ZipFile(SKELETON) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_skeleton_is_small(parts: dict[str, bytes]) -> None:
    size = os.path.getsize(SKELETON)
    assert size <= MAX_BYTES, f'Gerüst ist {size/1e6:.1f} MB — enthält es wieder Medien?'


def test_no_absolute_paths(parts: dict[str, bytes]) -> None:
    """Storyline merkt sich Herkunftspfade (``C:\\Users\\<konto>\\OneDrive - <Firma>``)."""
    pat = re.compile(rb'[A-Za-z]:\\\\?Users\\|/Users/|/home/')
    hits = [n for n, d in parts.items() if pat.search(d)]
    assert hits == []


def test_no_personal_metadata(parts: dict[str, bytes]) -> None:
    """OPC-Kerneigenschaften: Ersteller/Bearbeiter sind Benutzerkonten."""
    for name, data in parts.items():
        if not name.endswith('.psmdcp'):
            continue
        text = data.decode('utf-8', 'replace')
        for tag in ('dc:creator', 'lastModifiedBy'):
            m = re.search(rf'<{tag}>(.*?)</{tag}>', text)
            assert not (m and m.group(1).strip()), f'{tag} gesetzt: {m.group(1)!r}'


def test_media_are_placeholders(parts: dict[str, bytes]) -> None:
    """Die eingebetteten Medien werden von Layouts referenziert, ihr INHALT ist
    aber belanglos — sie müssen neutrale Platzhalter sein."""
    media = {n: d for n, d in parts.items() if n.startswith('story/media/')}
    assert media, 'keine Medien im Gerüst — Struktur unerwartet'
    total = sum(len(d) for d in media.values())
    assert total < 300_000, f'Medien belegen {total/1e6:.1f} MB — echte Inhalte?'


def test_no_embedded_preview_images(parts: dict[str, bytes]) -> None:
    """Folien-Vorschauen und Kursvorschaubild liegen als base64 im XML."""
    for name, data in parts.items():
        if not name.endswith('.xml'):
            continue
        for m in re.finditer(rb'[A-Za-z0-9+/]{4000,}={0,2}', data):
            pytest.fail(f'{name}: base64-Block mit {len(m.group(0))} Zeichen '
                        f'(Vorschaubild?)')


def test_no_course_text(parts: dict[str, bytes]) -> None:
    """Kurstexte in fmtText/plain — nur Storyline-Vorgabetexte sind erlaubt."""
    allowed = re.compile(
        r'^(\s*$|Text$|Folie$|Szene$|\s*(Click to edit|Question Choice|Button|'
        r'Feedback|Slide|Title|Picture|Seite %|&#x))', re.I)
    bad: list[str] = []
    for name, data in parts.items():
        if not name.endswith('.xml'):
            continue
        text = data.decode('utf-8', 'replace')
        for m in re.finditer(r'(?:&lt;|<)Span Text="([^"]{4,})"', text):
            if not allowed.match(m.group(1)):
                bad.append(f'{name}: {m.group(1)[:50]!r}')
    assert bad == [], f'{len(bad)} Kurstext(e) im Gerüst: {bad[:5]}'
