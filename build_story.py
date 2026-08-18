#!/usr/bin/env python3
"""
Storyline .story builder / experiment harness.

Konsolidiert alle bisherigen PoC-Erkenntnisse zur .ats -> .story Migration.
Baut Test-Stories durch Injektion in Folie 1 einer bekannten guten Vorlage.

BEWIESEN (siehe memory/story-format.md):
- Text rendert nur wenn <text> UND <fmtText> gesetzt sind.
- Bild-Bytes muessen non-interlaced PNG sein (PIL re-encode).
- Bindung pic -> media erfolgt ueber assetG -> <media g> ; media -> Datei ueber md5 (<stream>).
- md5 (<stream>) ist EINDEUTIGER Schluessel: Duplikat => "invalid or corrupt".
- Mediendatei als ZIP_DEFLATED schreiben.
- Bild-Bytes selbst rendern korrekt (hijack2 bewiesen). Offen: NEUER media-Eintrag.

EXPERIMENT-Schalter weiter unten in main().
"""
import zipfile, io, re, uuid, hashlib, html, datetime
from PIL import Image
import xml.etree.ElementTree as ET

TPL = 'reference.story'
ATS = 'kurs.ats'
NS  = '{http://im-c.de/xml/authoring/1.0}'

# Bekannte Anker in der Vorlage (Folie 1)
HALBRAD_GUID = '67cf4aca-098e-424f-b133-c9cff0e96e97'   # vorhandenes funktionierendes pic/media

ZERO = '00000000-0000-0000-0000-000000000000'


def ats_image(name='Der Weckruf'):
    """Groesstes PNG der genannten .ats-Animation, non-interlaced RGBA. -> (bytes, W, H, md5)."""
    ats = zipfile.ZipFile(ATS)
    root = ET.fromstring(ats.read('document/document.xml'))
    path = None
    for a in root.iter(NS + 'animation'):
        if a.get('name') == name:
            path = a.find('.//' + NS + 'resource').get('path'); break
    ata = zipfile.ZipFile(io.BytesIO(ats.read(path)))
    pngs = sorted([(n, ata.getinfo(n).file_size) for n in ata.namelist()
                   if n.endswith('.png') and 'thumbnail' not in n], key=lambda x: -x[1])
    im = Image.open(io.BytesIO(ata.read(pngs[0][0]))).convert('RGBA')
    buf = io.BytesIO(); im.save(buf, 'PNG', interlace=False)
    b = buf.getvalue()
    return b, im.width, im.height, hashlib.md5(b).hexdigest()


_B62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'


def media_filename(guid, ext):
    """Storyline leitet den Mediendateinamen aus der GUID ab (BEWIESEN 39/39):
    R + base62( int.from_bytes(GUID.bytes_le[:8], 'little') ) + '.' + ext.
    Falscher Name => Datei wird nicht gefunden => 'unreadable asset'."""
    n = int.from_bytes(uuid.UUID(guid).bytes_le[:8], 'little')
    s = ''
    if n == 0:
        s = _B62[0]
    while n:
        n, r = divmod(n, 62); s = _B62[r] + s
    return f'R{s}.{ext}'


def fmt_doc(text, size=26, color='#CC0000'):
    """Escaped Document/Block/Span fuer <text>/<fmtText>."""
    d = ('<Document xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Content><Block>'
         '<Style FlowDirection="LeftToRight" LeadingMargin="0" TrailingMargin="0" '
         'FirstLineMargin="0" Justification="Center" LineSpacingRule="Single" '
         'LineSpacing="20" SpacingBefore="0" SpacingAfter="0">'
         '<ListStyle ListType="None" ListTypeFormat="Parentheses" BulletFont="Arial" /></Style>'
         f'<Span Text="{html.escape(text)}"><Style FontFamily="Arial" FontSize="{size}" '
         f'FontIsBold="True" ForegroundColor="{color}" LinkColor="{color}" /></Span>'
         '</Block></Content></Document>')
    return d.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def extract_element(s, start, tag):
    """Vollstaendiges Element ab Index `start` (zeigt auf '<tag'), tag-balanciert.
    Beruecksichtigt VERSCHACHTELTE gleichnamige Tags (z.B. <pic> in <picFormat>)
    und ignoriert Praefix-Kollisionen (<picFormat>, </picFormat>) sowie self-closing."""
    op, cl = '<' + tag, '</' + tag + '>'
    depth, i = 0, start
    while i < len(s):
        no, nc = s.find(op, i), s.find(cl, i)
        if nc == -1:
            return None
        if no != -1 and no < nc:
            j = no + len(op)
            if j < len(s) and s[j] in ' >':            # echtes <tag ...> / <tag>
                gt = s.find('>', no)
                if s[gt - 1] != '/':                    # kein self-closing
                    depth += 1
                i = gt + 1
            else:                                       # Praefix wie <picFormat>
                i = no + len(op)
        else:
            depth -= 1
            i = nc + len(cl)
            if depth == 0:
                return s[start:i]
    return None


def reguid(frag, keep=()):
    """Alle GUIDs in frag durch neue ersetzen, ausser ZERO und in keep."""
    for g in set(re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', frag)):
        if g != ZERO and g not in keep:
            frag = frag.replace(g, str(uuid.uuid4()))
    return frag


def media_entry(guid, md5, nbytes, display, origfile):
    """Ein <media>-Element wie ein echter Storyline-Import."""
    now = datetime.datetime.now().isoformat()
    return (f'<media g="{guid}" verG="{uuid.uuid4()}" type="Png" displayName="{display}" '
            f'origFile="{html.escape(origfile)}" source="{html.escape(origfile)}" useCnt="0" '
            f'bytes="{nbytes}" modDT="{now}" addDT="{now}">'
            f'<md5Checksum><stream>{md5}</stream><source>{md5}</source></md5Checksum></media>')


def build(out, *, with_text=True, with_image=True,
          empty_paths=False, with_pic=True, with_rel=True,
          insert_at='front', reuse_asset=False):
    """Baue eine Test-Story. Schalter isolieren einzelne Faktoren.
    reuse_asset=True: geklontes pic zeigt auf das EXISTIERENDE halbes_rad-Asset
                      (KEIN neuer media-Eintrag, KEINE Datei, KEIN Rel) -> isoliert
                      'pic-Klon' von 'neuer Eintrag'."""
    z = zipfile.ZipFile(TPL)
    story = z.read('story/story.xml').decode('utf-8', 'replace')
    slide = z.read('story/slides/slide.xml').decode('utf-8', 'replace')
    rels  = z.read('story/slides/_rels/slide.xml.rels').decode('utf-8', 'replace')

    inject_shapes = ''
    new_files = {}        # zip-Pfad -> bytes

    # --- TEXT ---
    if with_text:
        i = slide.find('<textBox ')
        tb = reguid(extract_element(slide, i, 'textBox'))
        tb = re.sub(r'(<textBox [^>]*?) id="\d+"',   r'\g<1> id="11"', tb, count=1)
        tb = re.sub(r'(<textBox [^>]*?) name="[^"]*"', r'\g<1> name="ATS-Text-Test"', tb, count=1)
        tb = re.sub(r'<loc [^>]*/>', '<loc l="160" t="250" r="1120" b="320" />', tb, count=1)
        doc = fmt_doc('>> ATS-IMPORT TEST <<')
        tb = re.sub(r'<text>.*?</text>',       '<text>' + doc + '</text>', tb, count=1, flags=re.S)
        tb = re.sub(r'<fmtText>.*?</fmtText>', '<fmtText>' + doc + '</fmtText>', tb, count=1, flags=re.S)
        inject_shapes += tb

    # --- BILD ---
    if with_image:
        if reuse_asset:
            # KEIN neuer Eintrag/Datei/Rel: pic zeigt auf vorhandenes halbes_rad-Asset.
            guid, W, H = HALBRAD_GUID, 128, 128
        else:
            imgbytes, W, H, md5 = ats_image()
            guid = str(uuid.uuid4())
            fname = media_filename(guid, 'png')   # Name MUSS aus der GUID abgeleitet sein!
            origfile = '' if empty_paths else (
                r'C:\Users\import\AppData\Local\Temp\Articulate\Storyline\ats_DerWeckruf.png')

            # media-Eintrag in innere mediaLst
            me = media_entry(guid, md5, len(imgbytes), 'ats_DerWeckruf.png', origfile)
            if insert_at == 'front':
                story = story.replace('<media g=', me + '<media g=', 1)
            else:  # 'end' -> vor innerem </mediaLst>
                story = story.replace('</mediaLst></mediaLst>', me + '</mediaLst></mediaLst>', 1)

            new_files['story/media/' + fname] = imgbytes

        if with_pic:
            ps = slide.find('assetG="' + HALBRAD_GUID + '"')
            pstart = slide.rfind('<pic g=', 0, ps)
            pic = reguid(extract_element(slide, pstart, 'pic'), keep={HALBRAD_GUID})
            pic = pic.replace('assetG="' + HALBRAD_GUID + '"', 'assetG="' + guid + '"')
            pic = re.sub(r'(<pic [^>]*?) id="\d+"',   r'\g<1> id="12"', pic, count=1)
            pic = re.sub(r'(<pic [^>]*?) name="[^"]*"', r'\g<1> name="ATS-Bild-Test"', pic, count=1)
            tw = 240; th = int(tw * H / W); L = 520; T = 360
            pic = re.sub(r'<loc [^>]*/>', f'<loc l="{L}" t="{T}" r="{L+tw}" b="{T+th}" />', pic, count=1)
            pic = re.sub(r'<sourceRect [^>]*/>', f'<sourceRect l="0" t="0" r="{W}" b="{H}" />', pic, count=1)
            inject_shapes += pic

        if with_rel and not reuse_asset:
            rid = 'R' + uuid.uuid4().hex[:16]
            rels = rels.replace('</Relationships>',
                f'<Relationship Type="media" Target="/story/media/{fname}" Id="{rid}" /></Relationships>', 1)

    slide = slide.replace('</shapeLst>', inject_shapes + '</shapeLst>', 1)

    # --- repack ---
    zout = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
    for info in z.infolist():
        data = z.read(info.filename)
        if info.filename == 'story/story.xml': data = story.encode('utf-8')
        elif info.filename == 'story/slides/slide.xml': data = slide.encode('utf-8')
        elif info.filename == 'story/slides/_rels/slide.xml.rels': data = rels.encode('utf-8')
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr; zi.internal_attr = info.internal_attr
        zi.create_system = info.create_system
        zout.writestr(zi, data)
    for path, data in new_files.items():
        zi = zipfile.ZipInfo(path); zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    zout.close()
    bad = zipfile.ZipFile(out).testzip()
    print(f'{out:28s} text={with_text} img={with_image} pic={with_pic} rel={with_rel} '
          f'paths={"empty" if empty_paths else "real"} ins={insert_at} testzip={bad}')


# ============================================================================
#  ECHTE FOLIE: ganze .ats-Folie -> .story (alle Bilder, Letterbox-Skalierung)
# ============================================================================

# .ats Canvas und Letterbox-Mapping auf die 1280x720-Vorlage (Seitenverh. bleibt).
ATS_W, ATS_H = 1024, 748
SLD_W, SLD_H = 1280, 720
_SCALE = min(SLD_W / ATS_W, SLD_H / ATS_H)            # 0.96257
_OFFX  = (SLD_W - ATS_W * _SCALE) / 2                  # ~147.1
_OFFY  = (SLD_H - ATS_H * _SCALE) / 2                  # 0


def fit_rect(x, y, w, h):
    """.ats-Rect (1024x748) -> .story-loc (l,t,r,b), Letterbox-zentriert."""
    L = x * _SCALE + _OFFX
    T = y * _SCALE + _OFFY
    return L, T, (x + w) * _SCALE + _OFFX, (y + h) * _SCALE + _OFFY


def _morph_key():
    """Zufalls-morphKey (11 base62-Zeichen) wie im Original-propBag."""
    import random
    return ''.join(random.choice(_B62) for _ in range(11))


def ats_slide_images(ata_bytes):
    """Alle positionierten <image>-Shapes einer .ats-Folie in Dokument-/z-Reihenfolge.
    -> Liste von dict(name, rect=(x,y,w,h), png=bytes)."""
    ata = zipfile.ZipFile(io.BytesIO(ata_bytes))
    root = ET.fromstring(ata.read('document/document.xml'))
    out = []
    for e in root.iter(NS + 'image'):
        rect = res = None
        for cp in e.findall(NS + 'complexproperty'):
            if cp.get('name') == 'rect':  rect = cp.find(NS + 'rect')
            if cp.get('name') == 'image': res  = cp.find(NS + 'resource')
        if rect is None or res is None:
            continue
        path = res.get('path')
        if not path or path not in ata.namelist():
            continue
        out.append({
            'name': e.get('name') or 'Bild',
            'rect': (float(rect.get('x')), float(rect.get('y')),
                     float(rect.get('width')), float(rect.get('height'))),
            'png':  ata.read(path),
        })
    return out


def build_real_slide(out, ata_path, *, dur_ms=20500):
    """Baue EINE echte .ats-Folie in die Vorlagen-Folie (Shapes komplett ersetzt)."""
    z = zipfile.ZipFile(TPL)
    story = z.read('story/story.xml').decode('utf-8', 'replace')
    slide = z.read('story/slides/slide.xml').decode('utf-8', 'replace')
    rels  = z.read('story/slides/_rels/slide.xml.rels').decode('utf-8', 'replace')

    # pic-Stencil aus der Vorlage (bewiesen funktionierend).
    sp = slide.find('assetG="' + HALBRAD_GUID + '"')
    stencil = extract_element(slide, slide.rfind('<pic g=', 0, sp), 'pic')

    ats = zipfile.ZipFile(ATS)
    images = ats_slide_images(ats.read(ata_path))

    pics, media_entries, rel_lines, new_files = [], [], [], {}
    for zo, img in enumerate(images, start=1):
        # Bild non-interlaced re-encoden -> W,H,md5,bytes
        im = Image.open(io.BytesIO(img['png'])).convert('RGBA')
        buf = io.BytesIO(); im.save(buf, 'PNG', interlace=False)
        b = buf.getvalue(); W, H = im.width, im.height
        md5 = hashlib.md5(b).hexdigest()
        guid = str(uuid.uuid4())
        fname = media_filename(guid, 'png')
        new_files['story/media/' + fname] = b

        media_entries.append(media_entry(
            guid, md5, len(b), img['name'][:60] or 'Bild',
            r'C:\ats\\' + fname))
        rel_lines.append(
            f'<Relationship Type="media" Target="/story/media/{fname}" '
            f'Id="R{uuid.uuid4().hex[:16]}" />')

        # pic aus Stencil ableiten (HALBRAD behalten, damit das assetG-Replace greift)
        p = reguid(stencil, keep={HALBRAD_GUID})
        p = p.replace('assetG="' + HALBRAD_GUID + '"', 'assetG="' + guid + '"')
        p = re.sub(r'(<pic [^>]*?) id="\d+"',   rf'\g<1> id="{100 + zo}"', p, count=1)
        p = re.sub(r'(<pic [^>]*?) name="[^"]*"',
                   r'\g<1> name="' + html.escape(img['name'][:60]) + '"', p, count=1)
        p = re.sub(r'(<pic [^>]*?) zOrder="\d+"', rf'\g<1> zOrder="{zo}"', p, count=1)
        L, T, R, B = fit_rect(*img['rect'])
        p = re.sub(r'<loc [^>]*/>',
                   f'<loc l="{L:.4f}" t="{T:.4f}" r="{R:.4f}" b="{B:.4f}" />', p, count=1)
        p = re.sub(r'<sourceRect [^>]*/>',
                   f'<sourceRect l="0" t="0" r="{W}" b="{H}" />', p, count=1)
        p = re.sub(r'(<tmCtx [^>]*?) dur="\d+"', rf'\g<1> dur="{dur_ms}"', p, count=1)
        p = re.sub(r'<str>[0-9A-Za-z]{11}</str>', f'<str>{_morph_key()}</str>', p, count=1)
        pics.append(p)

    # Shapes der Vorlagen-Folie KOMPLETT ersetzen.
    assert slide.count('</shapeLst>') == 1, 'mehr als ein shapeLst!'
    slide = re.sub(r'(<shapeLst[^>]*>).*(</shapeLst>)',
                   lambda m: m.group(1) + ''.join(pics) + m.group(2),
                   slide, count=1, flags=re.S)

    # media-Eintraege in innere mediaLst (vor erstem vorhandenen <media g=).
    story = story.replace('<media g=', ''.join(media_entries) + '<media g=', 1)
    # Rels ergaenzen.
    rels = rels.replace('</Relationships>', ''.join(rel_lines) + '</Relationships>', 1)

    zout = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
    for info in z.infolist():
        data = z.read(info.filename)
        if info.filename == 'story/story.xml': data = story.encode('utf-8')
        elif info.filename == 'story/slides/slide.xml': data = slide.encode('utf-8')
        elif info.filename == 'story/slides/_rels/slide.xml.rels': data = rels.encode('utf-8')
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr; zi.internal_attr = info.internal_attr
        zi.create_system = info.create_system
        zout.writestr(zi, data)
    for path, data in new_files.items():
        zi = zipfile.ZipInfo(path); zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    zout.close()
    bad = zipfile.ZipFile(out).testzip()
    print(f'{out}: {len(images)} Bilder, testzip={bad}')
    return out


if __name__ == '__main__':
    # Erste ECHTE Folie: "Der Weckruf" (Intro-Kapitel), alle Bilder, Letterbox.
    build_real_slide('_PoC_real1.story',
                     'resources/ata/{3bf66f46-e697-41ef-a567-102d7714074f}.ata')
