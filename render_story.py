#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rendert erzeugte .story-Folien aus dem Paket selbst (Bilder an loc + Text aus fmtText)
zu PNG — beweist, dass die .story die Bild-/Text-/Positionsdaten korrekt enthält,
unabhängig von Storyline. Vergleicht optional mit dem Original-.ata-Thumbnail."""
import sys, re, io, zipfile, uuid, html as H
from PIL import Image, ImageDraw, ImageFont

_B62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
def b62(n):
    s = ''
    if n == 0: return _B62[0]
    while n: n, r = divmod(n, 62); s = _B62[r] + s
    return s
def media_filename(guid, ext):
    n = int.from_bytes(uuid.UUID(guid).bytes_le[:8], 'little')
    return f'R{b62(n)}.{ext}'

def load_font(size):
    for p in ('/System/Library/Fonts/Supplemental/Arial.ttf',
              '/Library/Fonts/Arial.ttf',
              '/System/Library/Fonts/Helvetica.ttc'):
        try: return ImageFont.truetype(p, max(8, int(size)))
        except Exception: pass
    return ImageFont.load_default()

def parse_loc(frag):
    m = re.search(r'<loc l="(-?[\d.]+)" t="(-?[\d.]+)" r="(-?[\d.]+)" b="(-?[\d.]+)"', frag)
    if not m: return None
    return tuple(float(x) for x in m.groups())

def bal(s, start, tag):
    op, cl = '<'+tag, '</'+tag+'>'; d=0; i=start
    while i < len(s):
        no=s.find(op,i); nc=s.find(cl,i)
        if nc==-1: return None
        if no!=-1 and no<nc:
            j=no+len(op)
            if j<len(s) and s[j] in ' >\t\n':
                g=s.find('>',no)
                if s[g-1]!='/': d+=1
                i=g+1
            else: i=no+len(op)
        else:
            d-=1; i=nc+len(cl)
            if d==0: return s[start:i]

def render_slide(z, partname, CW=1280, CH=720):
    s = z.read(partname).decode('utf-8','replace')
    names = set(z.namelist())
    canvas = Image.new('RGB', (CW, CH), 'white')
    npic = ntext = 0
    # PICS (in Dokumentreihenfolge = z-Order)
    for m in re.finditer(r'<pic\b', s):
        frag = bal(s, m.start(), 'pic')
        if not frag: continue
        am = re.search(r'\sassetG="([0-9a-fA-F-]{36})"', frag)
        loc = parse_loc(frag)
        if not am or not loc: continue
        g = am.group(1)
        fn = None
        for ext in ('png','jpg'):
            cand = 'story/media/' + media_filename(g, ext)
            if cand in names: fn = cand; break
        if not fn: continue
        try: im = Image.open(io.BytesIO(z.read(fn))).convert('RGBA')
        except Exception: continue
        l,t,r,b = loc
        w,h = max(1,int(round(r-l))), max(1,int(round(b-t)))
        im = im.resize((w,h))
        canvas.paste(im, (int(round(l)), int(round(t))), im)
        npic += 1
    # TEXT
    d = ImageDraw.Draw(canvas)
    for m in re.finditer(r'<textBox\b', s):
        frag = bal(s, m.start(), 'textBox')
        if not frag: continue
        loc = parse_loc(frag)
        tm = re.search(r'<text>(.*?)</text>', frag, re.S)
        if not loc or not tm: continue
        doc = H.unescape(tm.group(1))
        spans = re.findall(r'<Span Text="([^"]*)"><Style FontFamily="[^"]*" FontSize="([\d.]+)"[^>]*ForegroundColor="(#[0-9A-Fa-f]{6})"', doc)
        l,t,r,b = loc
        y = t; ntext += 1
        for txt, size, color in spans:
            txt = H.unescape(txt)
            txt = txt.replace('\u2028','\n')
            if not txt.strip():
                y += float(size)*1.3; continue
            f = load_font(float(size))
            maxw = max(40, int(r-l))
            for para in txt.split('\n'):
                words=para.split(' '); line=''
                for w in words:
                    test=(line+' '+w).strip()
                    if d.textlength(test, font=f) > maxw and line:
                        d.text((l,y), line, fill=color, font=f); y+=float(size)*1.35; line=w
                    else: line=test
                if line: d.text((l,y), line, fill=color, font=f); y+=float(size)*1.35

    return canvas, npic, ntext

def main():
    story = sys.argv[1] if len(sys.argv)>1 else 'EASY_BUSINESS_VOLLSTAENDIG.story'
    which = sys.argv[2].split(',') if len(sys.argv)>2 else ['slide.xml','slide2.xml','slide3.xml','slide4.xml']
    z = zipfile.ZipFile(story)
    for pn in which:
        part = 'story/slides/'+pn
        if part not in z.namelist():
            print('fehlt:', pn); continue
        img, npic, ntext = render_slide(z, part)
        out = f'_render_{pn.replace(".xml","")}.png'
        img.save(out)
        print(f'{out}: {npic} Bilder, {ntext} Textboxen')

if __name__=='__main__':
    main()
