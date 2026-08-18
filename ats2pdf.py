#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ats2pdf.py — rendert einen kompletten imc-.ats-Kurs als PDF (alle Folien, Bilder + Text,
in Originalreihenfolge). Audio kann ein PDF nicht enthalten (separate Mediathek nötig).

  python3 ats2pdf.py --out kurs.pdf
  python3 ats2pdf.py --chapters "Einleitung" --max-slides 10 --out test.pdf
  python3 ats2pdf.py --scale 2     # höhere Auflösung
"""
import argparse, io, re, zipfile, html as H
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

import ats2story as A   # walk_course, slide_content, parse_richtext, fit-Konstanten

CANVAS_W, CANVAS_H = A.ATS_W, A.ATS_H     # 1024 x 748


def font(size, bold=False, ital=False):
    base = '/System/Library/Fonts/Supplemental/'
    name = 'Arial'
    if bold and ital: name = 'Arial Bold Italic'
    elif bold: name = 'Arial Bold'
    elif ital: name = 'Arial Italic'
    for p in (base + name + '.ttf', base + 'Arial.ttf', '/Library/Fonts/Arial.ttf'):
        try: return ImageFont.truetype(p, max(6, int(round(size))))
        except Exception: pass
    return ImageFont.load_default()


def draw_text(d, blocks, rect, align, scale):
    x, y, w, h = rect
    x *= scale; y *= scale; w *= scale
    cy = y
    for runs in blocks:
        # Zeilen innerhalb des Blocks per Wortumbruch
        line_runs = []          # (text, style, font)
        # Block-Höhe grob: erst Wörter sammeln
        max_size = max((float(st['size']) for _, st in runs), default=14)
        f0 = font(max_size * scale)
        line = ''
        cx = x
        for text, st in runs:
            fnt = font(float(st['size']) * scale, st['bold'], st['ital'])
            color = A.norm_color(st['color'])
            for word in re.split(r'(\s+)', text):
                if not word: continue
                ww = d.textlength(word, font=fnt)
                if cx + ww > x + w and cx > x and word.strip():
                    cx = x; cy += max_size * scale * 1.3
                d.text((cx, cy), word, fill=color, font=fnt)
                cx += ww
        cy += max_size * scale * 1.45
    return cy


def render_slide(items, scale):
    W, H = int(CANVAS_W * scale), int(CANVAS_H * scale)
    canvas = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(canvas)
    for layer, kind, p in items:
        if kind == 'image':
            try:
                im = Image.open(io.BytesIO(p['bytes'])).convert('RGBA')
            except Exception:
                continue
            x, y, w, h = p['rect']
            box = (int(x * scale), int(y * scale))
            sz = (max(1, int(w * scale)), max(1, int(h * scale)))
            im = im.resize(sz)
            canvas.paste(im, box, im)
        elif kind == 'text':
            blocks = A.parse_richtext(p['rich'], p['elem'])
            draw_text(d, blocks, p['rect'], p.get('align', 'left'), scale)
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ats', default=A.DEF_ATS)
    ap.add_argument('--out', default='EASY_BUSINESS_kurs.pdf')
    ap.add_argument('--chapters', default=None)
    ap.add_argument('--max-slides', type=int, default=0)
    ap.add_argument('--scale', type=float, default=1.5)
    ap.add_argument('--no-exams', action='store_true')
    args = ap.parse_args()

    ats = zipfile.ZipFile(args.ats)
    scenes = A.walk_course(ats)
    if args.chapters:
        subs = [s.strip().lower() for s in args.chapters.split(',') if s.strip()]
        scenes = [sc for sc in scenes if any(x in sc['name'].lower() for x in subs)]

    pages = []
    n = 0
    for sc in scenes:
        for s in sc['slides']:
            if s.get('exam'):
                if args.no_exams:
                    continue
                img = Image.new('RGB', (int(CANVAS_W*args.scale), int(CANVAS_H*args.scale)), 'white')
                dd = ImageDraw.Draw(img)
                dd.text((60*args.scale, 320*args.scale), f'[ TEST ]  {s["name"]}',
                        fill='#CC0000', font=font(30*args.scale, bold=True))
                pages.append(img); n += 1
                continue
            items, audio = A.slide_content(s['ata'])
            pages.append(render_slide(items, args.scale))
            n += 1
            if n % 25 == 0:
                print(f'  ... {n} Folien gerendert')
            if args.max_slides and n >= args.max_slides:
                break
        if args.max_slides and n >= args.max_slides:
            break

    if not pages:
        print('Keine Folien.'); return
    print(f'Schreibe PDF mit {len(pages)} Seiten ...')
    pages[0].save(args.out, 'PDF', save_all=True, append_images=pages[1:], resolution=96.0)
    import os
    print(f'FERTIG: {args.out}  ({os.path.getsize(args.out)/1e6:.1f} MB, {len(pages)} Seiten)')


if __name__ == '__main__':
    main()
