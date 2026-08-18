#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für ats2story.guid."""
from __future__ import annotations

import uuid

from ats2story.guid import (
    GUID_RE,
    ZERO,
    b62,
    guid_b62,
    media_filename,
    newg,
    reguid,
    relid,
    relid_from_guid,
)


def test_b62_zero() -> None:
    assert b62(0) == '0'


def test_b62_roundtrip_base() -> None:
    # 62 -> '10' in base62
    assert b62(62) == '10'
    assert b62(61) == 'z'


def test_guid_b62_is_deterministic() -> None:
    g = '12345678-1234-5678-1234-567812345678'
    assert guid_b62(g) == guid_b62(g)


def test_media_filename_shape() -> None:
    g = str(uuid.uuid4())
    name = media_filename(g, 'png')
    assert name.startswith('R')
    assert name.endswith('.png')


def test_relid_from_guid_matches_media_short_id() -> None:
    g = str(uuid.uuid4())
    assert relid_from_guid(g) == 'R' + guid_b62(g)


def test_relid_random_has_prefix() -> None:
    r = relid()
    assert r.startswith('R')
    assert len(r) == 17


def test_newg_is_valid_guid() -> None:
    g = newg()
    assert GUID_RE.fullmatch(g)


def test_reguid_preserves_zero_and_preserve_set() -> None:
    keep = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    other = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    frag = f'<x g="{ZERO}" k="{keep}" o="{other}" />'
    out = reguid(frag, frozenset({keep}))
    assert ZERO in out
    assert keep in out
    assert other not in out  # wurde ersetzt


def test_reguid_is_consistent_for_same_guid() -> None:
    g = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
    frag = f'<a g="{g}"/><b g="{g}"/>'
    out = reguid(frag, frozenset())
    new_guids = GUID_RE.findall(out)
    assert len(new_guids) == 2
    assert new_guids[0] == new_guids[1]  # konsistente Abbildung
