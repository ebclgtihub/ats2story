#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose-Leiter: isoliert mögliche 'invalid or corrupt'-Ursachen Schicht für Schicht.

D1  reines Repack der Vorlage (0 Änderungen)         -> testet NUR mein ZIP-Packaging
D2  Vorlage komplett INTAKT + 1 .ats-Folie in slide1 -> testet Folien-/Medien-Erzeugung
    (keine Szenen-/toc-/quiz-Umbauten; alle 53 Originalfolien bleiben)
D3  voller Umbau, aber nur 3 Folien / 2 Szenen        -> testet Szenen-/toc-Umbau (= ats2story --max-slides 3)

Reihenfolge in Storyline öffnen; die ERSTE die scheitert zeigt die Schicht.
"""
import io, re, zipfile, hashlib
import xml.etree.ElementTree as ET
import ats2story as A


def repack(out):
    """D1: jeden Vorlagen-Part 1:1 mit erhaltenem ZipInfo neu schreiben."""
    z = zipfile.ZipFile(A.DEF_TPL)
    zout = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
    for info in z.infolist():
        data = z.read(info.filename)
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zi.internal_attr = info.internal_attr
        zi.create_system = info.create_system
        zout.writestr(zi, data)
    zout.close()
    print(f'D1 {out}: reines Repack, testzip={zipfile.ZipFile(out).testzip()}')


def one_slide(out, ata_path):
    """D2: Vorlage komplett intakt, nur slide.xml-Shapes durch EINE .ats-Folie ersetzt.
    Medienpool-Einträge in mediaLst (alte behalten), Rels ergänzt. Sonst NICHTS angefasst."""
    tpl = A.Template(A.DEF_TPL)
    pool = A.MediaPool()
    b = A.Builder(tpl, pool, with_audio=True)

    ats = zipfile.ZipFile(A.DEF_ATS)
    items, audio = A.slide_content(ats.read(ata_path))

    shapes = []
    used = []
    dur = A.MIN_DUR
    if audio:
        e = pool.add_audio(audio['bytes'], audio['name'])
        used.append(e); dur = max(dur, e['dur'] or dur)
        shapes.append(b._sound(e, dur))
    zo = 0
    for layer, kind, p in items:
        zo += 1
        if kind == 'image':
            e = pool.add_image(p['bytes'], p['name'])
            if e is None:
                zo -= 1; continue
            used.append(e)
            shapes.append(b._pic(e, p['rect'], p['name'], zo, dur, p.get('opacity', 100)))
        elif kind == 'text':
            blocks = A.parse_richtext(p['rich'], p['elem'])
            shapes.append(b._textbox(blocks, p['rect'], p['align'], zo + 100, atsrect=True))

    z = zipfile.ZipFile(A.DEF_TPL)
    slide = z.read('story/slides/slide.xml').decode('utf-8', 'replace')
    story = z.read('story/story.xml').decode('utf-8', 'replace')
    rels = z.read('story/slides/_rels/slide.xml.rels').decode('utf-8', 'replace')

    # Shapes ersetzen
    slide = re.sub(r'(<shapeLst[^>]*>).*?(</shapeLst>)',
                   lambda m: m.group(1) + ''.join(shapes) + m.group(2), slide, count=1, flags=re.S)
    ET.fromstring(slide.encode('utf-8'))

    # Medienpool-Einträge in innere mediaLst (alte behalten -> prepend)
    blob = ''.join(pool.entries_xml)
    OPEN = '<mediaLst><mediaLst>'
    a = story.find(OPEN)
    story = story[:a + len(OPEN)] + blob + story[a + len(OPEN):]
    ET.fromstring(story.encode('utf-8'))

    # Rels ergänzen (alte behalten)
    seen = set(); add = []
    for e in used:
        if e['fname'] in seen: continue
        seen.add(e['fname'])
        add.append(f'<Relationship Type="media" Target="/story/media/{e["fname"]}" Id="{A.relid()}" />')
    rels = rels.replace('</Relationships>', ''.join(add) + '</Relationships>')
    ET.fromstring(rels.encode('utf-8'))

    # Schreiben: alle Vorlagen-Parts + meine Medien
    zout = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
    for info in z.infolist():
        data = z.read(info.filename)
        if info.filename == 'story/slides/slide.xml': data = slide.encode('utf-8')
        elif info.filename == 'story/story.xml': data = story.encode('utf-8')
        elif info.filename == 'story/slides/_rels/slide.xml.rels': data = rels.encode('utf-8')
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type; zi.external_attr = info.external_attr
        zi.internal_attr = info.internal_attr; zi.create_system = info.create_system
        zout.writestr(zi, data)
    for path, data in pool.files.items():
        zi = zipfile.ZipInfo(path); zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    zout.close()
    print(f'D2 {out}: 1 .ats-Folie injiziert, {len(pool.files)} Medien, '
          f'testzip={zipfile.ZipFile(out).testzip()}')


if __name__ == '__main__':
    repack('_diag1_repack.story')
    # "Der Weckruf" als Inhaltsfolie (bild- + textreich + Audio)
    one_slide('_diag2_oneslide.story',
              'resources/ata/{3bf66f46-e697-41ef-a567-102d7714074f}.ata')
