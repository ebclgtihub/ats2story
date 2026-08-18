#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Konsistenz-Validator für erzeugte .story-Pakete.
Prüft alle Quer-Referenzen, die Storyline beim Öffnen verlangt."""
import sys, re, zipfile, hashlib
import xml.etree.ElementTree as ET

def main(path):
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    err = []; warn = []
    def E(m): err.append(m)
    def W(m): warn.append(m)

    story = z.read('story/story.xml').decode('utf-8','replace')
    rels  = z.read('story/_rels/story.xml.rels').decode('utf-8','replace')
    ct    = z.read('[Content_Types].xml').decode('utf-8','replace')

    # 1) Alle XML-Parts wohlgeformt
    bad_xml = 0
    for n in names:
        if n.endswith('.xml') or n.endswith('.rels'):
            try: ET.fromstring(z.read(n))
            except ET.ParseError as e:
                bad_xml += 1; E(f"XML kaputt: {n}: {e}")
    print(f"[1] XML wohlgeformt: {sum(1 for n in names if n.endswith(('.xml','.rels')))-bad_xml} ok, {bad_xml} kaputt")

    # 2) sldId -> story.xml.rels -> Part
    sldids = re.findall(r'<sldId>([^<]+)</sldId>', story)
    rel_map = dict(re.findall(r'<Relationship Type="slide" Target="([^"]+)" Id="([^"]+)" />', rels))
    # rel_map: target->id ; brauchen id->target
    id2tgt = {}
    for m in re.finditer(r'<Relationship Type="slide" Target="([^"]+)" Id="([^"]+)" />', rels):
        id2tgt[m.group(2)] = m.group(1)
    miss_rel = [s for s in sldids if s not in id2tgt]
    if miss_rel: E(f"{len(miss_rel)} sldId ohne Relationship: {miss_rel[:5]}")
    # Part existiert?
    miss_part = []
    for s in sldids:
        t = id2tgt.get(s)
        if t:
            p = t.lstrip('/')
            if p not in names: miss_part.append(p)
    if miss_part: E(f"{len(miss_part)} slide-Parts fehlen: {miss_part[:5]}")
    print(f"[2] sldId={len(sldids)}  slide-rels={len(id2tgt)}  fehlende rels={len(miss_rel)} fehlende parts={len(miss_part)}")

    # 3) Jeder slide-Part: Content-Types-Override + _rels-Datei + sld g
    sld_parts = sorted(n for n in names if re.match(r'story/slides/slide[0-9a-f]*\.xml$', n))
    ct_over = set(re.findall(r'<Override PartName="(/story/slides/slide[^"]*\.xml)"', ct))
    sld_guids = {}
    for p in sld_parts:
        if ('/'+p) not in ct_over: E(f"Content-Type Override fehlt: {p}")
        relp = p.replace('slides/','slides/_rels/')+'.rels'
        if relp not in names: E(f"_rels fehlt: {relp}")
        txt = z.read(p).decode('utf-8','replace')
        gm = re.search(r'<sld\b[^>]*\sg="([0-9a-fA-F-]{36})"', txt)
        if not gm: E(f"sld@g fehlt in {p}")
        else: sld_guids[p]=gm.group(1)
    print(f"[3] slide-Parts={len(sld_parts)}  ct-overrides={len(ct_over)}")

    # 4) toc: tocSceneEntry refG == scene g ; tocSlideEntry refG == sld g
    scene_guids = set(re.findall(r'<scene g="([0-9a-fA-F-]{36})"', story))
    toc_scene_ref = set(re.findall(r'<tocSceneEntry\b[^>]*\srefG="([0-9a-fA-F-]{36})"', story))
    toc_slide_ref = set(re.findall(r'<tocSlideEntry\b[^>]*\srefG="([0-9a-fA-F-]{36})"', story))
    bad_scene = toc_scene_ref - scene_guids
    if bad_scene: E(f"toc-Szenen-refG ohne scene: {len(bad_scene)}")
    all_sld_g = set(sld_guids.values())
    bad_slide = toc_slide_ref - all_sld_g
    if bad_slide: E(f"toc-Folien-refG ohne sld: {len(bad_slide)} z.B. {list(bad_slide)[:3]}")
    print(f"[4] scenes={len(scene_guids)} toc-scene-refs={len(toc_scene_ref)} toc-slide-refs={len(toc_slide_ref)} bad={len(bad_scene)}/{len(bad_slide)}")

    # 5) mediaLst: <media g> / <audio g> -> assetG in slides; md5 stream -> Datei
    media_guids = set(re.findall(r'<media g="([0-9a-fA-F-]{36})"', story))
    audio_guids = set(re.findall(r'<audio g="([0-9a-fA-F-]{36})"', story))
    pool_guids = media_guids | audio_guids
    # md5 streams
    streams = re.findall(r'<media g="([0-9a-fA-F-]{36})"[^>]*>.*?<stream>([0-9a-f]{32})</stream>', story)
    # einfacher: alle stream-md5 sammeln (media+audio)
    all_streams = re.findall(r'<stream>([0-9a-f]{32})</stream>', story)
    # Datei-md5
    file_md5 = {}
    for n in names:
        if n.startswith('story/media/'):
            file_md5[n.split('/')[-1]] = hashlib.md5(z.read(n)).hexdigest()
    md5_set = set(file_md5.values())
    streams_no_file = [s for s in all_streams if s not in md5_set]
    # (Hinweis: Vorlagen-Altmedien können stream ohne Datei haben -> nur zählen)
    print(f"[5] mediaLst: media={len(media_guids)} audio={len(audio_guids)} dateien={len(file_md5)} stream-md5-ohne-datei={len(streams_no_file)}")

    # 6) pic.assetG / sound.assetG -> Pool ; Slide-Rel-Media existiert als Datei
    asset_refs = 0; asset_missing = 0; rel_media_missing = 0; pics=0; sounds=0; texts=0
    file_in_some_rel = set()
    for p in sld_parts:
        txt = z.read(p).decode('utf-8','replace')
        pics += len(re.findall(r'<pic\b', txt)); sounds += len(re.findall(r'<sound\b', txt)); texts+=len(re.findall(r'<textBox\b', txt))
        for am in re.finditer(r'\sassetG="([0-9a-fA-F-]{36})"', txt):
            g = am.group(1)
            if g=='00000000-0000-0000-0000-000000000000': continue
            asset_refs += 1
            if g not in pool_guids: asset_missing += 1
        relp = p.replace('slides/','slides/_rels/')+'.rels'
        if relp in names:
            rtxt = z.read(relp).decode('utf-8','replace')
            for tm in re.finditer(r'Target="/story/media/([^"]+)"', rtxt):
                fn = tm.group(1); file_in_some_rel.add(fn)
                if ('story/media/'+fn) not in names: rel_media_missing += 1
    if asset_missing: E(f"{asset_missing} assetG ohne Pool-Eintrag")
    if rel_media_missing: E(f"{rel_media_missing} Rel-Media-Dateien fehlen")
    # Discovery: jede Datei sollte in einem Rel referenziert sein
    files_no_rel = [f for f in file_md5 if f not in file_in_some_rel]
    if files_no_rel: W(f"{len(files_no_rel)} Mediendateien in KEINEM slide-Rel (discovery!) z.B. {files_no_rel[:3]}")
    print(f"[6] pics={pics} sounds={sounds} textBoxes={texts} assetG-refs={asset_refs} fehlend={asset_missing} rel-media-fehlt={rel_media_missing} dateien-ohne-rel={len(files_no_rel)}")

    # 7) ALLE rels: jedes Target muss als Part existieren (dangling rel = "invalid or corrupt")
    dangling = []
    rel_count = 0
    for n in names:
        if not n.endswith('.rels'):
            continue
        base = n.replace('_rels/', '').rsplit('/', 1)[0]   # Basis-Verzeichnis des Parts
        txt = z.read(n).decode('utf-8','replace')
        for tm in re.finditer(r'Target="([^"]+)"', txt):
            t = tm.group(1)
            rel_count += 1
            if t.startswith('http'):
                continue
            if t.startswith('/'):
                p = t.lstrip('/')
            else:
                p = (base + '/' + t) if base else t
                # Pfad normalisieren (../)
                segs = []
                for s in p.split('/'):
                    if s == '..': segs and segs.pop()
                    elif s in ('', '.'): pass
                    else: segs.append(s)
                p = '/'.join(segs)
            if p not in names:
                dangling.append((n, t))
    if dangling:
        E(f"{len(dangling)} DANGLING rels (Target fehlt!): z.B. {dangling[:5]}")
    print(f"[7] Rels gesamt={rel_count}  dangling={len(dangling)}")

    print("\n=== ERRORS ===" if err else "\n=== KEINE FEHLER ===")
    for e in err: print(" !!", e)
    if warn:
        print("--- Warnungen ---")
        for w in warn: print("  ~", w)
    return 1 if err else 0

if __name__=='__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv)>1 else '_test_mini.story'))
