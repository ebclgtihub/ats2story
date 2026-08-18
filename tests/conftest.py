#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemeinsame pytest-Fixtures.

Sorgt dafür, dass das Projekt-Root im ``sys.path`` liegt, damit ``ats2story``
(das Paket) importierbar ist, egal von wo pytest gestartet wird.
"""
from __future__ import annotations

import glob
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

def _find_ats() -> str:
    """Beliebige lokale ``.ats`` als Regressions-Fixture (kleinste zuerst).

    Früher stand hier der Dateiname eines Kundenkurses fest verdrahtet — im
    Repository sichtbar, obwohl die Datei selbst per ``.gitignore`` draußen
    bleibt. ``ATS_FIXTURE`` setzt eine bestimmte Datei fest.
    """
    override = os.environ.get('ATS_FIXTURE')
    if override:
        return override
    hits = sorted(glob.glob(os.path.join(_ROOT, '*.ats')), key=os.path.getsize)
    return hits[0] if hits else os.path.join(_ROOT, 'kurs.ats')


#: Referenz für die Konformitätstests: eine Datei, die STORYLINE SELBST
#: geschrieben hat. Die lässt sich inhaltlich nicht von unseren eigenen
#: Ausgaben unterscheiden (die stammen ja von ihr ab), deshalb per Konvention:
#: ``reference.story`` im Projektwurzelverzeichnis — am einfachsten als Symlink
#: auf eine echte Storyline-Datei; oder ``ATS_FIXTURE_TPL`` setzen.
#: Die Datei bleibt durch ``*.story`` in ``.gitignore`` außerhalb des Repos.
REFERENCE_NAME = 'reference.story'

FIXTURE_ATS = _find_ats()
FIXTURE_TPL = os.environ.get('ATS_FIXTURE_TPL') or os.path.join(_ROOT, REFERENCE_NAME)


@pytest.fixture(scope='session')
def project_root() -> str:
    return _ROOT


@pytest.fixture(scope='session')
def fixture_ats() -> str:
    if not os.path.isfile(FIXTURE_ATS):
        pytest.skip(f'Regression-Fixture fehlt: {FIXTURE_ATS}')
    return FIXTURE_ATS


@pytest.fixture(scope='session')
def fixture_tpl() -> str:
    if not os.path.isfile(FIXTURE_TPL):
        pytest.skip(
            f'Referenz-Vorlage fehlt: {FIXTURE_TPL}\n'
            f'  Einmalig anlegen (bleibt durch .gitignore lokal):\n'
            f'    ln -s "MEINE_STORYLINE_DATEI.story" {REFERENCE_NAME}\n'
            f'  oder ATS_FIXTURE_TPL=<pfad> setzen.')
    return FIXTURE_TPL
