#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für die CLI (argparse, ohne echte Konvertierung)."""
from __future__ import annotations

import pytest

from ats2story import cli
from ats2story.converter import DEF_ATS


def test_parser_defaults() -> None:
    args = cli.build_parser().parse_args([])
    assert args.out == 'kurs.story'
    # Vorgabe ist die Originalgröße des Kurses (1:1), nicht das
    # 16:9-Einpassen — so kommt der Kurs unverändert an.
    assert args.geometry == 'native'
    assert args.no_audio is False
    assert args.max_slides == 0


def test_parser_positional_overrides_ats_flag() -> None:
    args = cli.build_parser().parse_args(['mein.ats', '--out', 'x.story'])
    assert args.ats_pos == 'mein.ats'
    assert args.out == 'x.story'


def test_parser_flag_form() -> None:
    args = cli.build_parser().parse_args(['--ats', 'flag.ats', '--geometry', 'fill'])
    assert args.ats == 'flag.ats'
    assert args.geometry == 'fill'
    assert args.ats_pos is None


def test_main_uses_positional_then_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_convert(ats, out, **kw):
        seen['ats'] = ats
        seen['out'] = out
        seen['geometry'] = kw.get('geometry')
        return {}

    monkeypatch.setattr(cli, 'convert_ats', fake_convert)
    cli.main(['pos.ats', '--out', 'o.story', '--no-audio', '--geometry', 'fill'])
    assert seen['ats'] == 'pos.ats'         # positional gewinnt
    assert seen['out'] == 'o.story'
    assert seen['geometry'] == 'fill'


def test_main_defaults_to_def_ats(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    monkeypatch.setattr(cli, 'convert_ats',
                        lambda ats, out, **kw: seen.update(ats=ats) or {})
    cli.main(['--out', 'o.story'])
    assert seen['ats'] == DEF_ATS           # ohne positional/--ats -> Default
