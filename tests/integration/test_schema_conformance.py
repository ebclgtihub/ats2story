#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema-Konformität gegen eine von Storyline SELBST geschriebene Datei.

Ob Storyline eine erzeugte ``.story`` wirklich öffnet, lässt sich ohne
Storyline nicht beweisen. Beweisbar ist das, woran OPC-Formate praktisch
scheitern („invalid or corrupt"): ein Element, ein Attribut oder ein
Aufzählungswert, den die Anwendung selbst nie schreibt — oder ein Pflichtfeld,
das fehlt.

Referenz ist die mitgelieferte Vorlage; sie stammt aus Storyline und enthält
über 80 000 Elemente. Diese Tests vergleichen unsere Folien-XML dagegen.
"""
from __future__ import annotations

import collections
import html
import re
import zipfile

import pytest

import ats2story

_SLIDE = re.compile(r'story/slides/slide[0-9a-f]*\.xml$')
_TAG = re.compile(r'<([a-zA-Z][\w.-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*/?>')
_ATTR = re.compile(r'\s+([\w:.-]+)="([^"]*)"')

#: Attribute mit freien Werten (IDs, Maße, Farben, Namen) — hier ist nur die
#: EXISTENZ prüfbar, nicht die Wertemenge.
_FREE_VALUE = re.compile(
    r'^(g|verG|id|name|assetG|zOrder|state|typeName|initState|trigG|start|dur|'
    r'min|max|cur|l|t|r|b|w|h|x|y|val|Text|assetStart|sz|blur|angle|dist|'
    r'spread|alpha|scale|adjustY|FontFamily|FontSize|BulletFont|ForegroundColor|'
    r'BackgroundColor|UnderlineColor|LinkColor|Color|LineSpacing|Size|Offset)$')


def _profile(path: str):
    """Tag-/Attribut-/Wert-Profil aller Folien-XML einer .story."""
    attrs = collections.defaultdict(set)
    values = collections.defaultdict(set)
    tags = collections.Counter()
    pairs = collections.Counter()
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not _SLIDE.match(n):
                continue
            s = html.unescape(z.read(n).decode('utf-8', 'replace'))
            for m in _TAG.finditer(s):
                tag = m.group(1)
                tags[tag] += 1
                for a in _ATTR.finditer(m.group(2)):
                    attrs[tag].add(a.group(1))
                    pairs[(tag, a.group(1))] += 1
                    if not _FREE_VALUE.match(a.group(1)) and len(a.group(2)) <= 40:
                        values[(tag, a.group(1))].add(a.group(2))
    return attrs, values, tags, pairs


@pytest.fixture(scope='module')
def profiles(tmp_path_factory, fixture_ats: str, fixture_tpl: str):
    out = str(tmp_path_factory.mktemp('conform') / 'conform.story')
    ats2story.convert_ats(fixture_ats, out, tpl=fixture_tpl, max_slides=6,
                          no_audio=True, progress=lambda f, m: None)
    return _profile(fixture_tpl), _profile(out)


def test_no_element_storyline_never_writes(profiles) -> None:
    (_ra, _rv, r_tags, _rp), (_ca, _cv, c_tags, _cp) = profiles
    assert r_tags, 'Referenzprofil leer — Vorlage ohne Folien?'
    assert sorted(set(c_tags) - set(r_tags)) == []


def test_no_attribute_storyline_never_writes(profiles) -> None:
    (r_attrs, _rv, _rt, _rp), (c_attrs, _cv, _ct, _cp) = profiles
    unknown = sorted((t, a) for t in c_attrs for a in c_attrs[t]
                     if t in r_attrs and a not in r_attrs[t])
    assert unknown == []


def test_no_mandatory_attribute_missing(profiles) -> None:
    """Attribute, die Storyline bei einem Element IMMER setzt, müssen auch bei
    uns an jedem Vorkommen stehen."""
    (r_attrs, _rv, r_tags, r_pairs), (_ca, _cv, c_tags, c_pairs) = profiles
    missing = []
    for tag, cnt in c_tags.items():
        if tag not in r_tags:
            continue
        for attr in r_attrs.get(tag, ()):
            if r_pairs[(tag, attr)] == r_tags[tag] and c_pairs[(tag, attr)] < cnt:
                missing.append((tag, attr))
    assert sorted(missing) == []


def test_enum_values_are_known_to_storyline(profiles) -> None:
    """Aufzählungswerte (kleine Wertemenge in der Referenz) müssen dort
    vorkommen — z.B. ``LineSpacingRule="Exactly"`` oder ``rot="-1"``."""
    (_ra, r_vals, _rt, _rp), (_ca, c_vals, _ct, _cp) = profiles
    bad = []
    for (tag, attr), vals in c_vals.items():
        ref = r_vals.get((tag, attr))
        if not ref or len(ref) > 25:
            continue                       # keine Aufzählung
        for v in vals - ref:
            if not re.fullmatch(r'-?[\d.]+', v):
                bad.append((tag, attr, v, sorted(ref)[:6]))
    assert bad == []


def test_zip_entry_names_are_posix(tmp_path, fixture_ats: str, fixture_tpl: str) -> None:
    """OPC-Pfade müssen IMMER Schrägstriche haben — auch wenn gebaut auf Windows.

    Ein ``os.path.join`` beim Zusammensetzen von ZIP-Namen würde dort
    Backslashes erzeugen und das Paket für Storyline unlesbar machen. Die Namen
    entstehen deshalb per String-Verkettung; dieser Test hält das fest.
    """
    out = str(tmp_path / 'posix.story')
    ats2story.convert_ats(fixture_ats, out, tpl=fixture_tpl, max_slides=3,
                          no_audio=True, progress=lambda f, m: None)
    with zipfile.ZipFile(out) as z:
        bad = [n for n in z.namelist() if '\\' in n or n.startswith('/')]
    assert bad == []
