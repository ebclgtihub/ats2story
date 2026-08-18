#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hinweis auf neuere Fassungen.

Die Prüfung läuft beim Start und darf unter keinen Umständen stören: kein
Netz, eine Sperre oder eine unerwartete Antwort müssen folgenlos bleiben.
Ein falscher Alarm ist ausserdem lästiger als ein ausgelassener — im Zweifel
also KEIN Hinweis.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'converter_app'))
import updates  # noqa: E402


@pytest.mark.parametrize('text,expected', [
    ('1.0.2', (1, 0, 2)),
    ('v1.0.2', (1, 0, 2)),
    ('V2.10.0', (2, 10, 0)),
    ('1.0.2-beta', (1, 0, 2)),
    ('1.0', (1, 0)),
    ('', ()),
    (None, ()),
    ('ohne Zahlen', ()),
])
def test_parse_version(text, expected) -> None:
    assert updates.parse_version(text) == expected


@pytest.mark.parametrize('latest,current,newer', [
    ('1.0.3', '1.0.2', True),
    ('v1.0.3', '1.0.2', True),
    ('1.1.0', '1.0.9', True),
    ('2.0', '1.9.9', True),
    ('1.0.2', '1.0.2', False),      # gleich -> kein Hinweis
    ('1.0.1', '1.0.2', False),      # älter -> kein Hinweis
    ('1.0', '1.0.0', False),        # 1.0 == 1.0.0
    ('kaputt', '1.0.2', False),     # unlesbar -> lieber nichts sagen
    ('1.0.3', '', False),
])
def test_is_newer(latest, current, newer) -> None:
    assert updates.is_newer(latest, current) is newer


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub(monkeypatch, payload, exc=None):
    def fake(req, timeout=0):
        if exc:
            raise exc
        return _Resp(json.dumps(payload).encode('utf-8'))

    monkeypatch.setattr(updates.urllib.request, 'urlopen', fake)


def test_reads_tag_and_link(monkeypatch) -> None:
    _stub(monkeypatch, {'tag_name': 'v1.0.5', 'name': '1.0.5',
                        'html_url': f'https://github.com/{updates.REPO}/releases/tag/v1.0.5'})
    rel = updates.latest_release()
    assert rel['version'] == '1.0.5'
    assert rel['url'].endswith('v1.0.5')


def test_no_network_is_silent(monkeypatch) -> None:
    """Im abgeschotteten Netz ist das der Normalfall, kein Fehler."""
    _stub(monkeypatch, {}, exc=urllib.error.URLError('kein Netz'))
    assert updates.latest_release() is None
    assert updates.check('1.0.2') is None


def test_garbage_answer_is_ignored(monkeypatch) -> None:
    _stub(monkeypatch, ['keine', 'Zuordnung'])
    assert updates.latest_release() is None
    _stub(monkeypatch, {'tag_name': 'ohne Zahlen'})
    assert updates.latest_release() is None


def test_check_only_reports_something_newer(monkeypatch) -> None:
    _stub(monkeypatch, {'tag_name': 'v1.0.2'})
    assert updates.check('1.0.2') is None
    _stub(monkeypatch, {'tag_name': 'v1.0.3'})
    assert updates.check('1.0.2')['version'] == '1.0.3'


def test_version_is_the_one_from_the_package() -> None:
    """Zwei Quellen driften auseinander; pyproject leitet sie deshalb ab."""
    import ats2story

    text = (Path(__file__).resolve().parents[2] / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'dynamic = ["version"]' in text
    assert 'attr = "ats2story.__version__"' in text
    assert updates.parse_version(ats2story.__version__), 'Version unlesbar'


# --- Herunterladen und Einspielen ------------------------------------------
# Ab hier lädt die App eine ausführbare Datei. Jede dieser Prüfungen steht für
# einen Weg, auf dem etwas Fremdes ins Programm käme.
import hashlib  # noqa: E402
import os  # noqa: E402


def _asset(data: bytes, **over) -> dict:
    a = dict(name='ATS-Converter-macOS.zip',
             browser_download_url=f'https://github.com/{updates.REPO}/releases/download/v9/x.zip',
             size=len(data),
             digest='sha256:' + hashlib.sha256(data).hexdigest())
    a.update(over)
    return a


class _DL(io.BytesIO):
    status = 200

    def __init__(self, data, url=None):
        super().__init__(data)
        self._url = url or f'https://github.com/{updates.REPO}/releases/download/v9/x.zip'

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, data, url=None):
    monkeypatch.setattr(updates.urllib.request, 'urlopen',
                        lambda req, timeout=0: _DL(data, url))


def test_download_checks_out(monkeypatch, tmp_path) -> None:
    data = b'x' * 5000
    _serve(monkeypatch, data)
    path = updates.download_verified(_asset(data), str(tmp_path))
    assert open(path, 'rb').read() == data


def test_wrong_checksum_is_thrown_away(monkeypatch, tmp_path) -> None:
    """Der wichtigste Fall: die Datei ist nicht die angekündigte."""
    data = b'x' * 5000
    _serve(monkeypatch, b'y' * 5000)           # etwas ANDERES kommt an
    with pytest.raises(updates.UpdateError, match='Prüfsumme'):
        updates.download_verified(_asset(data), str(tmp_path))
    assert not os.listdir(tmp_path), 'halbe Datei blieb liegen'


def test_missing_checksum_refuses(monkeypatch, tmp_path) -> None:
    """Ohne Prüfsumme wird NICHT geladen — kein blindes Vertrauen."""
    data = b'x' * 100
    _serve(monkeypatch, data)
    with pytest.raises(updates.UpdateError, match='Prüfsumme'):
        updates.download_verified(_asset(data, digest=''), str(tmp_path))


def test_foreign_host_refused(monkeypatch, tmp_path) -> None:
    data = b'x' * 100
    _serve(monkeypatch, data)
    for bad in ('https://boese.example/x.zip',
                f'http://github.com/{updates.REPO}/releases/download/v9/x.zip'):
        with pytest.raises(updates.UpdateError, match='Herkunft'):
            updates.download_verified(_asset(data, browser_download_url=bad), str(tmp_path))


def test_redirect_to_foreign_host_refused(monkeypatch, tmp_path) -> None:
    """Die Adresse stimmt, die Weiterleitung führt woanders hin."""
    data = b'x' * 100
    _serve(monkeypatch, data, url='https://boese.example/x.zip')
    with pytest.raises(updates.UpdateError, match='fremden Rechner'):
        updates.download_verified(_asset(data), str(tmp_path))
    assert not os.listdir(tmp_path)


def test_size_mismatch_refused(monkeypatch, tmp_path) -> None:
    data = b'x' * 5000
    _serve(monkeypatch, data)
    with pytest.raises(updates.UpdateError):
        updates.download_verified(_asset(data, size=6000), str(tmp_path))
    assert not os.listdir(tmp_path)


def test_oversized_download_is_cut_off(monkeypatch, tmp_path) -> None:
    """Sonst könnte eine angekündigt kleine Datei die Platte füllen."""
    _serve(monkeypatch, b'x' * 50_000)
    with pytest.raises(updates.UpdateError, match='größer'):
        updates.download_verified(_asset(b'x' * 100, size=100), str(tmp_path))


def test_asset_matches_the_running_system() -> None:
    rel = {'assets': [{'name': 'ATS-Converter-Setup.exe'},
                      {'name': 'ATS-Converter-macOS.zip'},
                      {'name': 'ATS-Converter-macOS.dmg'}]}
    import platform
    got = updates.asset_for_this_system(rel)
    assert got and got['name'] == updates.ASSET_FOR[platform.system()]
    assert updates.asset_for_this_system({'assets': []}) is None
