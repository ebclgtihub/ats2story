#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt das App-Symbol für Windows (.ico) und macOS (.icns).

Gezeichnet statt gemalt: das Symbol wird bei jedem Build aus diesem Skript
erzeugt, damit es in jeder Größe scharf bleibt und niemand eine 16-px-Fassung
von Hand nachpflegen muss.

Das Motiv ist der Gegenstand des Werkzeugs: eine Folie geht nach rechts über
in eine zweite. Links die imc-Folie in Weiß, rechts die Storyline-Folie im
Arbeitsblau der App, dazwischen der Pfeil. Unter 32 px fallen die Textzeilen
in der Folie weg — dort zählt nur noch die Silhouette.

Aufruf:  python3 packaging/make_icon.py [Zielverzeichnis]
"""
from __future__ import annotations

import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

#: Farben der App (converter_app/web/style.css)
INK = (14, 19, 25, 255)          # --paper dunkel: fast schwarz, blaustichig
INK_2 = (26, 35, 47, 255)        # Verlauf nach oben
PAPER = (255, 255, 255, 255)
MARK = (47, 124, 214, 255)       # helleres --mark, damit es auf Dunkel trägt
MARK_DEEP = (31, 95, 168, 255)
LINE = (170, 180, 192, 255)

SIZE = 1024


def _rounded(draw: ImageDraw.ImageDraw, box, r: int, fill) -> None:
    draw.rounded_rectangle(box, radius=r, fill=fill)


def render(px: int) -> Image.Image:
    """Das Symbol in der Kantenlänge ``px``."""
    s = SIZE / 1024
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Hintergrund: abgerundetes Quadrat mit sanftem Verlauf nach oben.
    _rounded(d, (0, 0, SIZE - 1, SIZE - 1), int(224 * s), INK)
    grad = Image.new('RGBA', (1, SIZE))
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE):
        k = (1 - y / SIZE) * 0.55
        gd.point((0, y), fill=tuple(int(a + (b - a) * k) for a, b in zip(INK, INK_2)))
    mask = Image.new('L', (SIZE, SIZE), 0)
    _rounded(ImageDraw.Draw(mask), (0, 0, SIZE - 1, SIZE - 1), int(224 * s), 255)
    img.paste(grad.resize((SIZE, SIZE)), (0, 0), mask)
    d = ImageDraw.Draw(img)

    detail = px >= 32          # Textzeilen erst ab dieser Größe

    # EINE Folie, im Verhältnis des Gegenstands (1024:748), und ein Pfeil
    # daneben. Zwei Folien mit Pfeil dazwischen sahen bei 1024 px gut aus, bei
    # 32 px aber nur noch nach Gekrümel — die Silhouette muss auch klein
    # eindeutig sein: heller Block links, blaue Spitze rechts.
    fx0, fy0 = int(112 * s), int(330 * s)
    fw, fh = int(496 * s), int(362 * s)
    r = int(34 * s)

    # Weicher Schatten unter der Folie, damit sie auf dem Dunkel aufliegt.
    sh = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    _rounded(ImageDraw.Draw(sh), (fx0, fy0 + int(16 * s), fx0 + fw, fy0 + fh + int(20 * s)),
             r, (0, 0, 0, 110))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(int(18 * s))))
    d = ImageDraw.Draw(img)

    _rounded(d, (fx0, fy0, fx0 + fw, fy0 + fh), r, PAPER)
    if detail:
        for i, w in enumerate((0.74, 0.52, 0.64)):
            y = fy0 + int((72 * s) + i * (74 * s))
            _rounded(d, (fx0 + int(52 * s), y,
                         fx0 + int(52 * s) + int((fw - int(104 * s)) * w), y + int(30 * s)),
                     int(15 * s), LINE if i else MARK_DEEP)

    # Pfeil rechts daneben, waagerecht — auf gleicher Höhe wie die Folie.
    cy = fy0 + fh // 2
    x0 = fx0 + fw + int(56 * s)
    x1 = int(942 * s)
    th = int(74 * s)
    head = int(150 * s)
    d.rounded_rectangle((x0, cy - th // 2, x1 - head + int(20 * s), cy + th // 2),
                        radius=int(12 * s), fill=MARK)
    d.polygon([(x1, cy),
               (x1 - head, cy - head * 3 // 4),
               (x1 - head, cy + head * 3 // 4)], fill=MARK)

    return img.resize((px, px), Image.LANCZOS)


def build(outdir: str) -> dict[str, str]:
    os.makedirs(outdir, exist_ok=True)
    made: dict[str, str] = {}

    png = os.path.join(outdir, 'icon.png')
    render(1024).save(png)
    made['png'] = png

    # Windows: mehrere Größen in EINER .ico — Explorer nimmt je nach Ansicht
    # eine andere; fehlt die kleine, skaliert er die große und es verschmiert.
    ico = os.path.join(outdir, 'icon.ico')
    sizes = [16, 24, 32, 48, 64, 128, 256]
    render(256).save(ico, sizes=[(s, s) for s in sizes])
    made['ico'] = ico

    # macOS: iconset -> icns. iconutil gibt es nur dort; sonst Pillow.
    icns = os.path.join(outdir, 'icon.icns')
    iconset = os.path.join(outdir, 'icon.iconset')
    os.makedirs(iconset, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        render(base).save(os.path.join(iconset, f'icon_{base}x{base}.png'))
        render(base * 2).save(os.path.join(iconset, f'icon_{base}x{base}@2x.png'))
    if sys.platform == 'darwin':
        subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', icns], check=True)
    else:
        render(512).save(icns, format='ICNS')
    made['icns'] = icns
    return made


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    for kind, path in build(out).items():
        print(f'  {kind:4} -> {path} ({os.path.getsize(path) // 1024} KB)')
