#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lädt eine .story-Vorlage und extrahiert Folien-Stencils + Preserve-Set."""
from __future__ import annotations

import hashlib
import re
import zipfile

from ..geometry import extract_element, find_first
from ..guid import GUID_RE, ZERO


class Template:
    """Bekannte gute .story-Vorlage; liefert Versions-Ceremony + Stencils.

    Lädt alle Parts in den Speicher (``self.parts``) und extrahiert aus
    ``story/slides/slide.xml`` die Stencils für pic/textBox/sound sowie das
    Slide-Skelett. Sammelt zudem GUIDs aus Masters/Layouts/Theme (Preserve-Set)
    und die von Nicht-Slide-Parts referenzierten Medien (keep_media_files).
    """

    def __init__(self, path: str) -> None:
        with zipfile.ZipFile(path) as z:
            self.parts = {i.filename: z.read(i.filename) for i in z.infolist()}
            self.infos = {i.filename: i for i in z.infolist()}
            self.order = [i.filename for i in z.infolist()]
        self._stencils()

    def _stencils(self) -> None:
        slide = self.parts['story/slides/slide.xml'].decode('utf-8', 'replace')
        self.slide_raw = slide

        # PIC-Stencil: erstes <pic> mit assetG != ZERO und <sourceRect>
        pic = None
        self.pic_asset = ZERO
        for m in re.finditer(r'<pic\b', slide):
            frag = extract_element(slide, m.start(), 'pic')
            if frag and 'assetG="' in frag and '<sourceRect' in frag:
                am = re.search(r'assetG="([0-9a-fA-F-]{36})"', frag)
                if am and am.group(1) != ZERO:
                    pic = frag
                    self.pic_asset = am.group(1)
                    break
        self.pic_stencil = pic

        # TEXTBOX-Stencil
        tb = None
        ti = find_first(slide, '<textBox')
        if ti >= 0:
            tb = extract_element(slide, ti, 'textBox')
        self.tb_stencil = tb

        # SOUND-Stencil
        snd = None
        si = find_first(slide, '<sound')
        if si >= 0:
            snd = extract_element(slide, si, 'sound')
        self.snd_stencil = snd
        self.snd_asset = ZERO
        if snd:
            am = re.search(r'<sound\b[^>]*\sassetG="([0-9a-fA-F-]{36})"', snd)
            self.snd_asset = am.group(1) if am else ZERO

        # SLIDE-Skelett: shapeLst-Inhalt -> {SHAPES}, slide-level trigLst leeren
        sk = slide
        m = re.search(r'(<shapeLst[^>]*>).*?(</shapeLst>)', sk, re.S)
        sk = sk[:m.start()] + '<shapeLst>{SHAPES}</shapeLst>' + sk[m.end():]
        sc = sk.find('</shapeLst>')
        ti = sk.find('<trigLst', sc)
        if ti >= 0:
            tl = extract_element(sk, ti, 'trigLst')
            if tl:
                sk = sk[:ti] + '<trigLst />' + sk[ti + len(tl):]
        # bg auf weiß
        sk = re.sub(r'(<bg>.*?<foreClr><srgbClr val=")[0-9A-Fa-f]{6}("\s*/></foreClr>)',
                    r'\g<1>FFFFFF\g<2>', sk, count=1, flags=re.S)
        self.slide_skeleton = sk

        # Preserve-Set: GUIDs aus Masters/Layouts/Theme/Styles/story.xml
        preserve: set[str] = set()
        for fn, data in self.parts.items():
            if (fn.startswith('story/slideMasters/') or fn.startswith('story/slideLayouts/')
                    or fn.startswith('story/theme/') or fn in (
                        'story/defaultStyles.xml', 'story/story.xml',
                        'story/playerProps.xml', 'story/viewProps.xml')):
                for g in GUID_RE.findall(data.decode('utf-8', 'replace')):
                    preserve.add(g.lower())
        self.preserve = preserve
        self.story = self.parts['story/story.xml'].decode('utf-8', 'replace')
        self.story_rels = self.parts['story/_rels/story.xml.rels'].decode('utf-8', 'replace')
        self.ctypes = self.parts['[Content_Types].xml'].decode('utf-8', 'replace')

        # Medien, die NICHT-slide-Parts referenzieren, MÜSSEN erhalten bleiben.
        self.keep_media_files: set[str] = set()
        for fn, data in self.parts.items():
            if fn.endswith('.rels') and not fn.startswith('story/slides/_rels/'):
                for t in re.findall(r'Target="(/story/media/[^"]+)"', data.decode('utf-8', 'replace')):
                    self.keep_media_files.add(t.lstrip('/'))
        self.keep_md5 = {hashlib.md5(self.parts[f]).hexdigest()
                         for f in self.keep_media_files if f in self.parts}
