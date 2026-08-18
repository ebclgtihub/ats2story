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
