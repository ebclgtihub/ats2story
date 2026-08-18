#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patcht story.xml (sceneLst/toc/mediaLst/quiz) und baut summary/rels."""
from __future__ import annotations

import html
import re

from ..geometry import extract_element
from ..guid import ZERO, guid_b62, newg


def patch_story_xml(story: str, scenes_built: list[dict]) -> str:
    """Ersetzt sceneLst + toc + pG passend zur neuen Folienstruktur.

    ``scenes_built``: ``[{name, scene_guid, sldids:[relid...],
    slides:[{relid, sld_guid, ...}]}]``.
    """
    scene_xml = []
    toc_scene = []
    for sc in scenes_built:
        sg = sc['scene_guid']
        ids = ''.join(f'<sldId>{r}</sldId>' for r in sc['sldids'])
        scene_xml.append(
            f'<scene g="{sg}" verG="{newg()}" name="{html.escape(sc["name"][:80])}" desc="" '
            f'primaryId="{ZERO}" sceneType="scene" collapse="false"><sldIdLst>{ids}</sldIdLst></scene>')
        toc_slides = ''.join(
            f'<tocSlideEntry g="{newg()}" verG="{newg()}" refG="{s["sld_guid"]}" corG="{newg()}" '
            f'expanded="true"><entryLst /></tocSlideEntry>' for s in sc['slides'])
        toc_scene.append(
            f'<tocSceneEntry g="{newg()}" verG="{newg()}" refG="{sg}" corG="{newg()}" '
            f'expanded="true"><entryLst>{toc_slides}</entryLst></tocSceneEntry>')

    new_sceneLst = '<sceneLst>' + ''.join(scene_xml) + '</sceneLst>'
    story = re.sub(r'<sceneLst>.*?</sceneLst>', lambda m: new_sceneLst, story, count=1, flags=re.S)

    # toc komplett neu bauen (balanciert extrahieren -> ersetzen)
    ti = re.search(r'<toc\b', story)
    if ti:
        toc_frag = extract_element(story, ti.start(), 'toc')
        open_tag = toc_frag[:toc_frag.find('>') + 1]
        new_toc = (open_tag + '<entryLst>' + ''.join(toc_scene) + '</entryLst><deleted /></toc>')
        story = story[:ti.start()] + new_toc + story[ti.start() + len(toc_frag):]

    # story.pG zeigt auf die erste Szene — und wenn es keine gibt, auf nichts.
    # Blieb dort die GUID der Vorlage stehen, verwies der Kurs auf eine Szene,
    # die es nicht mehr gab.
    pg = scenes_built[0]['scene_guid'] if scenes_built else ZERO
    story = re.sub(r'(<story\b[^>]*?) pG="[0-9a-fA-F-]{36}"',
                   rf'\g<1> pG="{pg}"', story, count=1)
    return story


def set_story_size(tpl, w: int, h: int) -> None:
    """Story-Size der Vorlage umstellen (z.B. auf 1024x748 für geometry='native').

    Regex-basiert (analog ``clean_backgrounds``), patcht die bereits
    extrahierten Template-Attribute in-place:

    1. ``tpl.story``: ``<prop id="15"><sz w h /></prop>`` (die Story-Size).
    2. ``tpl.pic_stencil`` / ``tpl.tb_stencil`` / ``tpl.snd_stencil`` /
       ``tpl.slide_skeleton``: alle ``<sldSz w h />`` (jedes Shape trägt eine
       Kopie der Slide-Größe vor seinem ``<loc>``) sowie die ``<sz>`` in den
       propBag-Einträgen ``oldsize``/``oldDesignedSlideSizeProp``.

    Layouts/Masters werden bewusst NICHT angefasst — Storyline toleriert den
    Mismatch nachweislich und reskaliert zur Laufzeit.
    """
    sz = f'<sz w="{w}" h="{h}" />'
    sldsz = f'<sldSz w="{w}" h="{h}" />'
    tpl.story = re.sub(
        r'(<prop id="15">)<sz\s+w="\d+"\s+h="\d+"\s*/>',
        lambda m: m.group(1) + sz, tpl.story, count=1)

    def _patch(frag: str | None) -> str | None:
        if frag is None:
            return None
        frag = re.sub(r'<sldSz\s+w="\d+"\s+h="\d+"\s*/>', lambda m: sldsz, frag)
        frag = re.sub(
            r'((?:oldsize|oldDesignedSlideSizeProp)</key><val>)<sz\s+w="\d+"\s+h="\d+"\s*/>',
            lambda m: m.group(1) + sz, frag)
        return frag

    tpl.pic_stencil = _patch(tpl.pic_stencil)
    tpl.tb_stencil = _patch(tpl.tb_stencil)
    tpl.snd_stencil = _patch(tpl.snd_stencil)
    tpl.slide_skeleton = _patch(tpl.slide_skeleton)


def add_media_pool(story: str, pool, keep_md5: set[str]) -> str:
    """Innere mediaLst neu: neuer Pool + erhaltene Alt-Einträge (md5 in keep_md5)."""
    OPEN, CLOSE = '<mediaLst><mediaLst>', '</mediaLst></mediaLst>'
    a = story.find(OPEN)
    b = story.find(CLOSE)
    if a == -1 or b == -1:
        return story
    inner = story[a + len(OPEN):b]
    kept = []
    i = 0
    while i < len(inner):
        m = re.compile(r'<(media|audio)\b').search(inner, i)
        if not m:
            break
        frag = extract_element(inner, m.start(), m.group(1))
        if frag is None:
            break
        sm = re.search(r'<stream>([0-9a-f]{32})</stream>', frag)
        if sm and sm.group(1) in keep_md5:
            kept.append((m.group(1), frag))
        i = m.start() + len(frag)
    kept_media = [f for k, f in kept if k == 'media']
    kept_audio = [f for k, f in kept if k == 'audio']
    # Invariante: ALLE <media> zuerst, dann ALLE <audio>
    new_inner = ''.join(pool.media_xml) + ''.join(kept_media) + ''.join(pool.audio_xml) + ''.join(kept_audio)
    return story[:a + len(OPEN)] + new_inner + story[b:]


def build_summary(scenes_built: list[dict]) -> str:
    """docProps/summary.xml passend zur neuen Struktur (Outline/Publish-Cache)."""
    n = sum(len(sc['slides']) for sc in scenes_built)
    if scenes_built and scenes_built[0]['slides']:
        sg = guid_b62(scenes_built[0]['scene_guid'])
        fg = guid_b62(scenes_built[0]['slides'][0]['sld_guid'])
        start = f'_player.{sg}.{fg}'
    else:
        start = '_player'
    parts = ['﻿<?xml version="1.0" encoding="utf-8"?>'
             '<summary xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
             f'<publish slidecount="{n}" additionalstepcount="-1" navigationcount="{n}" '
             f'startobjectpath="{html.escape(start)}" requiresplayertopbar="false" '
             'requiresplayerbottombar="false" /><scenes>']
    for sc in scenes_built:
        parts.append(f'<scene name="{html.escape(sc["name"][:80])}" g="{sc["scene_guid"]}"><slides>')
        for s in sc['slides']:
            parts.append(f'<slide name="{html.escape(s["name"][:80])}" g="{s["sld_guid"]}" '
                         f'verG="{s["verg"]}" note="" thumbnail="" />')
        parts.append('</slides></scene>')
    parts.append('</scenes></summary>')
    return ''.join(parts)


def strip_quiz(story: str, bank_scene: str = '') -> str:
    """Fragenbank setzen (oder leeren) und tote Ergebnis-Verweise nullen.

    Die Vorlage bringt eine Bank mit Folien mit, die es hier nicht mehr gibt —
    bliebe sie stehen, verwiese sie ins Leere und Storyline lehnte die Datei
    ab. ``bank_scene`` ersetzt sie durch die aus dem imc-Depot gebaute Bank.
    """
    inner = f'<bankLst>{bank_scene}</bankLst>' if bank_scene else '<bankLst />'
    story = re.sub(r'<bankLst>.*?</bankLst>|<bankLst\s*/>',
                   lambda m: inner, story, count=1, flags=re.S)
    story = re.sub(r'(\b(?:lmsResultSlideG|resultSldG|passedQuizzesG|failedQuizzesG)=)"[0-9a-fA-F-]{36}"',
                   rf'\g<1>"{ZERO}"', story)
    return story


def build_story_rels(slides_built: list) -> list[str]:
    """Gerüst für story.xml.rels (wird im Konverter mit Vorlagen-rels gefüllt)."""
    rels = ['<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    return rels
