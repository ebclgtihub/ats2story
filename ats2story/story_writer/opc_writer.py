#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schreibt das fertige .story-OPC-ZIP-Paket."""
from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..media import MediaPool
    from .template import Template


def write_story_package(out: str, tpl: 'Template', story: str, rels: str, ctypes: str,
                        summary_xml: str, new_slide_parts: dict[str, bytes],
                        new_slide_rels: dict[str, bytes], pool: 'MediaPool',
                        keep_medialst: bool) -> object:
    """Schreibt alle Parts (gepatchte Vorlage + neue Folien + Medien) als ZIP.

    Vorlagen-Folien/-rels und nicht mehr referenzierte Vorlagen-Medien werden
    gedroppt. Gibt das Ergebnis von ``testzip()`` zurück (None = ok).
    """
    drop = set()
    for fn in tpl.parts:
        if fn.startswith('story/slides/slide') and fn.endswith('.xml'):
            drop.add(fn)
        if fn.startswith('story/slides/_rels/'):
            drop.add(fn)
        # Medien nur droppen, wenn nicht von Layouts/Masters/story-rels gebraucht
        if fn.startswith('story/media/') and fn not in tpl.keep_media_files and not keep_medialst:
            drop.add(fn)

    written: set[str] = set()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:

        def write(fn: str, data: bytes, info=None, deflate: bool = True) -> None:
            if fn in written:
                return
            written.add(fn)
            if info is not None:
                zi = zipfile.ZipInfo(fn, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.internal_attr = info.internal_attr
                zi.create_system = info.create_system
            else:
                zi = zipfile.ZipInfo(fn)
                zi.compress_type = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
            zout.writestr(zi, data)

        # Vorlagen-Parts (ohne gedroppte), mit Patches
        for fn in tpl.order:
            if fn in drop:
                continue
            data = tpl.parts[fn]
            if fn == 'story/story.xml':
                data = story.encode('utf-8')
            elif fn == 'story/_rels/story.xml.rels':
                data = rels.encode('utf-8')
            elif fn == '[Content_Types].xml':
                data = ctypes.encode('utf-8')
            elif fn == 'docProps/summary.xml':
                data = summary_xml.encode('utf-8')
            write(fn, data, tpl.infos[fn])

        # neue Folien + rels
        for fn, data in new_slide_parts.items():
            write(fn, data)
        for fn, data in new_slide_rels.items():
            write(fn, data)
        # Medien
        for fn, data in pool.files.items():
            write(fn, data, deflate=True)

    with zipfile.ZipFile(out) as _tz:
        return _tz.testzip()
