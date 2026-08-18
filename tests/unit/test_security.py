#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für ats2story.security (zip-slip / zip-bomb Guards)."""
from __future__ import annotations

import io
import zipfile

import pytest

from ats2story.security import IMG_PIXEL_MAX, ZIP_MEMBER_MAX, safe_zip_read


def _zip_with(name: str, data: bytes) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_safe_zip_read_reads_normal_member() -> None:
    z = _zip_with('document/document.xml', b'<root/>')
    assert safe_zip_read(z, 'document/document.xml') == b'<root/>'


def test_safe_zip_read_rejects_absolute_path() -> None:
    z = _zip_with('ok.txt', b'x')
    with pytest.raises(ValueError, match='Zip-slip'):
        safe_zip_read(z, '/etc/passwd')


def test_safe_zip_read_rejects_parent_traversal() -> None:
    z = _zip_with('ok.txt', b'x')
    with pytest.raises(ValueError, match='Zip-slip'):
        safe_zip_read(z, '../../secret')


def test_safe_zip_read_rejects_oversized_member(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cap künstlich klein setzen, dann normalen Member als "bomb" sehen.
    import ats2story.security as sec

    monkeypatch.setattr(sec, 'ZIP_MEMBER_MAX', 4)
    z = _zip_with('big.bin', b'0123456789')
    with pytest.raises(ValueError, match='Zip-bomb'):
        sec.safe_zip_read(z, 'big.bin')


def test_caps_are_positive() -> None:
    assert ZIP_MEMBER_MAX > 0
    assert IMG_PIXEL_MAX == 4096 * 4096
