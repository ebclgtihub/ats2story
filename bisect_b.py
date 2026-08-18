#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BISECT B: Template KOMPLETT intakt (originale story.xml, alle 53 Folien, originale
mediaLst), NUR slide.xml durch eine von ats2story.Builder erzeugte Folie ersetzt
(mit der ORIGINAL-sld-GUID, damit sceneLst/toc/summary weiter passen). Meine Medien
werden — wie beim funktionierenden _PoC_real1 — der mediaLst vorangestellt und die
Rels angehängt. Öffnet das -> meine Folien-Erzeugung ist Storyline-gültig."""
import zipfile, re, io
import ats2story as A

TPL = A.DEF_TPL
ATS = A.DEF_ATS
OUT = '_BISECT_B_slidegen.story'

ORIG_SLD_G   = '8ec70877-92b0-49ff-a456-ab37b0dab87b'   # slide.xml <sld g>
ORIG_SLD_VG  = 'b685ec46-6332-4ed8-865d-b7f1c6d92341'   # slide.xml <sld verG>

tpl = A.Template(TPL)
ats = zipfile.ZipFile(ATS)
scenes = A.walk_course(ats)
first = scenes[0]['slides'][0]            # Start-Folie (Text+Bilder+Audio)

pool = A.MediaPool()
builder = A.Builder(tpl, pool, with_audio=True)
sld_xml, rels_xml, sld_guid, dur, used = builder.build_slide(first, 'slide.xml', 0)

# sld-GUID/verG auf ORIGINAL zwingen, damit toc/summary/sceneLst weiter referenzieren
sld_xml = re.sub(r'(<sld\b[^>]*?) g="[0-9a-fA-F-]{36}"',  rf'\g<1> g="{ORIG_SLD_G}"',  sld_xml, count=1)
sld_xml = re.sub(r'(<sld\b[^>]*?) verG="[0-9a-fA-F-]{36}"', rf'\g<1> verG="{ORIG_SLD_VG}"', sld_xml, count=1)
import xml.etree.ElementTree as ET
ET.fromstring(sld_xml.encode('utf-8'))

# story.xml: meine <media> nach OPEN, meine <audio> vor CLOSE (Reihenfolge media-vor-audio wahren)
story = tpl.story
OPEN = '<mediaLst><mediaLst>'
CLOSE = '</mediaLst></mediaLst>'
a = story.find(OPEN); b = story.find(CLOSE)
story = (story[:a + len(OPEN)] + ''.join(pool.media_xml) + story[a + len(OPEN):b]
         + ''.join(pool.audio_xml) + story[b:])
ET.fromstring(story.encode('utf-8'))

# slide.xml.rels: ORIGINAL-Rels + meine Medien-Rels (mergen, BOM behalten)
orig_rels = tpl.parts['story/slides/_rels/slide.xml.rels'].decode('utf-8', 'replace')
my_rel_lines = re.findall(r'<Relationship[^>]*/>', rels_xml)
merged = orig_rels.replace('</Relationships>', ''.join(my_rel_lines) + '</Relationships>')
ET.fromstring(merged.encode('utf-8'))

# ---- packen: alles original, nur slide.xml + dessen rels + story.xml ersetzt, Medien dazu ----
zout = zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED)
for info in tpl.z.infolist():
    fn = info.filename
    data = tpl.parts[fn]
    if fn == 'story/story.xml':
        data = story.encode('utf-8')
    elif fn == 'story/slides/slide.xml':
        data = sld_xml.encode('utf-8')
    elif fn == 'story/slides/_rels/slide.xml.rels':
        data = merged.encode('utf-8')
    zi = zipfile.ZipInfo(fn, date_time=info.date_time)
    zi.compress_type = info.compress_type
    zi.external_attr = info.external_attr
    zi.internal_attr = info.internal_attr
    zi.create_system = info.create_system
    zout.writestr(zi, data)
for path, data in pool.files.items():
    zi = zipfile.ZipInfo(path); zi.compress_type = zipfile.ZIP_DEFLATED
    zout.writestr(zi, data)
zout.close()
print(f'{OUT}: geschrieben. meine Medien={len(pool.files)}, sld-GUID erzwungen={ORIG_SLD_G}')
print('testzip:', zipfile.ZipFile(OUT).testzip())
