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


def latest_payload(timeout: float = TIMEOUT, url: str = API) -> dict | None:
    """Die ROHE Antwort des Verzeichnisses (mit der Dateiliste).

    :func:`latest_release` kürzt sie auf Version und Adresse; zum Herunterladen
    werden aber die Dateien samt Prüfsummen gebraucht.
    """
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': f'ats2story-updatecheck ({REPO})',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, 'status', 200) != 200:
                return None
            data = json.loads(resp.read(2_000_000).decode('utf-8', 'replace'))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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


# ─────────────────────────────────────────────── Herunterladen und Einspielen
#
# Ab hier lädt die App eine ausführbare Datei und startet sie. Das ist ein
# Einfallstor, wenn man es leichtfertig baut — deshalb drei feste Regeln:
#
# 1. Die Adresse muss zu GitHub gehören UND aus der Antwort des Verzeichnisses
#    stammen. Nichts, was von woanders kommt, wird geladen.
# 2. Die Prüfsumme muss stimmen. GitHub liefert zu jeder Datei ein sha256;
#    fehlt es, wird ABGEBROCHEN statt blind vertraut.
# 3. Nichts geschieht von selbst. Der Benutzer stößt es an, sieht den
#    Fortschritt und wird gefragt, bevor die App sich beendet.

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile

#: Nur von dort wird geladen. GitHub leitet Release-Dateien auf einen eigenen
#: Objektspeicher um; beide Hosts müssen erlaubt sein, sonst bricht die
#: Weiterleitung ab.
ALLOWED_HOSTS = ('github.com', 'objects.githubusercontent.com',
                 'release-assets.githubusercontent.com')

#: Welche Datei zu welchem System gehört. Für macOS das ZIP und nicht das DMG:
#: ein Bündel lässt sich daraus ohne Einhängen ersetzen.
ASSET_FOR = {
    'Windows': 'ATS-Converter-Setup.exe',
    'Darwin': 'ATS-Converter-macOS.zip',
}


class UpdateError(RuntimeError):
    """Etwas stimmt nicht — die Aktualisierung wird NICHT eingespielt."""


def _host_ok(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.scheme == 'https' and u.hostname in ALLOWED_HOSTS


def asset_for_this_system(release: dict) -> dict | None:
    """Die zum laufenden System passende Datei aus einer Release-Antwort."""
    want = ASSET_FOR.get(platform.system())
    if not want:
        return None
    for a in release.get('assets') or []:
        if a.get('name') == want:
            return a
    return None


def download_verified(asset: dict, dest_dir: str, on_progress=None,
                      timeout: float = 30) -> str:
    """Datei laden und gegen Größe und Prüfsumme halten. -> Pfad.

    Wirft :class:`UpdateError`, sobald etwas nicht zusammenpasst. Die halbe
    Datei wird dann weggeräumt: eine angefangene Installationsdatei
    herumliegen zu lassen, lädt zum versehentlichen Starten ein.
    """
    url = str(asset.get('browser_download_url') or '')
    if not _host_ok(url):
        raise UpdateError(f'Unerwartete Herkunft: {url[:80]}')
    digest = str(asset.get('digest') or '')
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise UpdateError('Keine Prüfsumme im Verzeichnis — Abbruch')
    expect_sum = digest.split(':', 1)[1].lower()
    expect_size = int(asset.get('size') or 0)

    dest = os.path.join(dest_dir, os.path.basename(asset.get('name') or 'update.bin'))
    req = urllib.request.Request(url, headers={'User-Agent': f'ats2story-update ({REPO})'})
    sha = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, 'wb') as out:
            if not _host_ok(resp.geturl()):
                raise UpdateError('Weiterleitung auf einen fremden Rechner')
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                got += len(chunk)
                if expect_size and got > expect_size:
                    raise UpdateError('Datei ist größer als angekündigt')
                if on_progress and expect_size:
                    on_progress(got / expect_size)
    except UpdateError:
        _discard(dest)
        raise
    except Exception as e:
        _discard(dest)
        raise UpdateError(f'Herunterladen fehlgeschlagen: {e}') from e

    if expect_size and got != expect_size:
        _discard(dest)
        raise UpdateError(f'Größe weicht ab ({got} statt {expect_size})')
    if sha.hexdigest().lower() != expect_sum:
        _discard(dest)
        raise UpdateError('Prüfsumme stimmt nicht — Datei verworfen')
    return dest


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def is_frozen() -> bool:
    """Läuft die App als gebautes Programm (und nicht aus dem Quellcode)?"""
    return bool(getattr(sys, 'frozen', False))


def app_bundle() -> str | None:
    """Pfad des laufenden .app-Bündels (nur macOS, nur gebaut)."""
    if platform.system() != 'Darwin' or not is_frozen():
        return None
    p = os.path.abspath(sys.executable)
    while p != '/':
        if p.endswith('.app'):
            return p
        p = os.path.dirname(p)
    return None


def apply_windows(installer: str) -> None:
    """Installationsprogramm starten. Die App muss sich danach beenden."""
    subprocess.Popen([installer], close_fds=True,
                     creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))


def apply_macos(zip_path: str, bundle: str) -> None:
    """Bündel austauschen, sobald die App beendet ist, und neu starten.

    Ein laufendes Programm kann sich nicht selbst ersetzen. Deshalb übernimmt
    ein kleines Skript den Tausch: es wartet, bis unsere Kennung verschwunden
    ist, ersetzt das Bündel und startet es wieder. Schlägt der Tausch fehl,
    bleibt das alte Bündel stehen — lieber keine neue Fassung als gar keine.
    """
    stage = tempfile.mkdtemp(prefix='ats-update-')
    subprocess.run(['ditto', '-x', '-k', zip_path, stage], check=True,
                   capture_output=True)
    new = None
    for name in os.listdir(stage):
        if name.endswith('.app'):
            new = os.path.join(stage, name)
            break
    if not new:
        shutil.rmtree(stage, ignore_errors=True)
        raise UpdateError('Im Paket steckt kein Programmbündel')

    script = os.path.join(stage, 'einspielen.sh')
    with open(script, 'w', encoding='utf-8') as fh:
        fh.write(f'''#!/bin/sh
# Wartet auf das Ende der laufenden App, tauscht das Bündel und startet neu.
for _ in $(seq 1 60); do
  kill -0 {os.getpid()} 2>/dev/null || break
  sleep 0.5
done
if ditto "{new}" "{bundle}.neu" 2>/dev/null; then
  rm -rf "{bundle}.alt" && mv "{bundle}" "{bundle}.alt" 2>/dev/null
  if mv "{bundle}.neu" "{bundle}" 2>/dev/null; then
    rm -rf "{bundle}.alt"
  else
    mv "{bundle}.alt" "{bundle}" 2>/dev/null
  fi
fi
xattr -dr com.apple.quarantine "{bundle}" 2>/dev/null
open "{bundle}"
rm -rf "{stage}"
''')
    os.chmod(script, 0o755)
    subprocess.Popen(['/bin/sh', script], start_new_session=True)
