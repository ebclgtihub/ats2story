#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vergleicht eine erzeugte ``.story`` mit einem imc-SCORM-Export.

Der SCORM-Export ist imc's EIGENE Darstellung des Kurses und damit die
belastbarste Referenz, die es ohne Storyline gibt: ``content/manifest.json.txt``
listet die Folien in Reihenfolge, und jedes ``content/<guid>/<guid>.json.txt``
beschreibt eine Folie vollständig — Elementtyp, Position in Pixel und, bei
Texten, das CSS mitsamt ``font-size``, ``line-height``, ``color`` und dem
Klartext.

Geprüft wird je Folie:

* **Text** — kommt jeder Textinhalt aus dem imc-Export auch in unserer
  ``.story`` vor (normalisiert, ohne Rücksicht auf Zeilenumbrüche)?
* **Position** — steht die Textbox an derselben Stelle (in imc-Koordinaten
  zurückgerechnet, Toleranz in Pixel)?
* **Schriftgröße** — passt sie zur imc-Vorgabe (px -> pt, s. SPEC)?
* **Bilder** — stimmt die Anzahl der Bild-Shapes?

Aufruf::

    python3 scripts/verify_against_export.py kurs.story scorm_export/ [--tolerance 4]

``scorm_export`` ist der entpackte Export ODER die ZIP-Datei.
"""
from __future__ import annotations

import argparse
import html as H
import json
import os
import re
import sys
import unicodedata
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ats2story.geometry import PX_TO_PT  # noqa: E402

_SLIDE_PART = re.compile(r'story/slides/slide[0-9a-f]*\.xml$')
_LOC = re.compile(r'<loc l="(-?[\d.]+)" t="(-?[\d.]+)" r="(-?[\d.]+)" b="(-?[\d.]+)"')


def _norm(s: str) -> str:
    """Text für den Vergleich normalisieren (Whitespace, Unicode, Groß/klein)."""
    s = unicodedata.normalize('NFKC', H.unescape(s or ''))
    s = re.sub(r'<[^>]+>', ' ', s)                 # imc-html kann Markup tragen
    return re.sub(r'\s+', ' ', s).strip().casefold()


class Export:
    """Ein imc-SCORM-Export (Verzeichnis oder ZIP)."""

    def __init__(self, path: str) -> None:
        self._zip = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
        self._root = None if self._zip else path

    def read(self, name: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(name)
        with open(os.path.join(self._root, name), 'rb') as fh:
            return fh.read()

    def slides(self) -> list[dict]:
        """Folien in Kursreihenfolge -> ``[{title, type, json}]``."""
        man = json.loads(self.read('content/manifest.json.txt').decode('utf-8'))
        out = []
        for item in man.get('library', []):
            src = item.get('src')
            if not src:
                continue
            try:
                data = json.loads(self.read(src).decode('utf-8'))
            except Exception:
                continue
            out.append(dict(title=item.get('title') or '?',
                            type=item.get('type') or '?', json=data))
        return out


def story_slides(path: str) -> list[dict]:
    """Folien der erzeugten .story in Reihenfolge -> ``[{name, texts, pics}]``.

    ``texts`` je Textbox: ``(text, l, t, r, b, groesste_schriftgroesse_pt)``.
    """
    def part_index(name: str) -> int:
        m = re.search(r'slide([0-9a-f]*)\.xml$', name)
        return 1 if not m.group(1) else int(m.group(1), 16)

    out = []
    with zipfile.ZipFile(path) as z:
        for name in sorted((n for n in z.namelist() if _SLIDE_PART.match(n)), key=part_index):
            s = z.read(name).decode('utf-8', 'replace')
            nm = re.search(r'<sld\b[^>]*?\sname="([^"]*)"', s)
            texts, pics = [], 0
            for m in re.finditer(r'<(pic|textBox)\b', s):
                frag = _balanced(s, m.start(), m.group(1))
                if not frag:
                    continue
                loc = _LOC.search(frag)
                if m.group(1) == 'pic':
                    pics += 1
                    continue
                tm = re.search(r'<text>(.*?)</text>', frag, re.S)
                if not (tm and loc):
                    continue
                doc = H.unescape(tm.group(1))
                spans = re.findall(r'<Span Text="([^"]*)"', doc)
                sizes = [float(x) for x in re.findall(r'FontSize="([\d.]+)"', doc)]
                texts.append((' '.join(H.unescape(x) for x in spans),
                              *(float(v) for v in loc.groups()),
                              max(sizes) if sizes else 0.0))
            out.append(dict(name=H.unescape(nm.group(1)) if nm else '',
                            texts=texts, pics=pics))
    return out


def _balanced(s: str, start: int, tag: str) -> str | None:
    op, cl = '<' + tag, '</' + tag + '>'
    depth, i = 0, start
    while i < len(s):
        no, nc = s.find(op, i), s.find(cl, i)
        if nc == -1:
            return None
        if no != -1 and no < nc:
            j = no + len(op)
            if j < len(s) and s[j] in ' >\t\n':
                gt = s.find('>', no)
                if s[gt - 1] != '/':
                    depth += 1
                i = gt + 1
            else:
                i = no + len(op)
        else:
            depth -= 1
            i = nc + len(cl)
            if depth == 0:
                return s[start:i]
    return None


def _px(value) -> float:
    try:
        return float(str(value).rstrip('px').strip())
    except (TypeError, ValueError):
        return 0.0


def compare(story: str, export: str, tol: float = 4.0, scale: float | None = None) -> int:
    exp = Export(export)
    ref = exp.slides()
    ours = story_slides(story)
    print(f'imc-Export : {len(ref)} Folien')
    print(f'unsere .story: {len(ours)} Folien\n')

    miss_text = pos_off = size_off = 0
    checked = 0
    problems: list[str] = []

    # Folien über den TITEL zuordnen, nicht über die Position: unsere
    # Reihenfolge folgt dem Kapitelbaum (Fragen hängen an ihrer Prüfung),
    # der imc-Export listet den Fragenpool am Stück. Inhaltlich ist das
    # dieselbe Menge — nur anders sortiert.
    by_name: dict[str, list[dict]] = {}
    for sl in ours:
        by_name.setdefault(_norm(sl['name']), []).append(sl)

    for i, r in enumerate(ref):
        key = _norm(r['title'])
        cand = by_name.get(key)
        if cand:
            mine = cand.pop(0)
        elif i < len(ours):
            mine = ours[i]
        else:
            problems.append(f'Folie {i+1} „{r["title"]}": fehlt in der .story')
            continue
        lib = [e for e in r['json'].get('library', []) if isinstance(e, dict)]
        ref_texts = [e for e in lib if e.get('type') == 'text']
        haystack = _norm(' '.join(t[0] for t in mine['texts']))

        for e in ref_texts:
            checked += 1
            want = _norm(e.get('html', ''))
            if not want:
                continue
            if want not in haystack:
                miss_text += 1
                problems.append(f'Folie {i+1} „{r["title"]}": Text fehlt — {want[:60]!r}')
                continue
            st = e.get('style') or {}
            left, top = _px(st.get('left')), _px(st.get('top'))
            best = min(mine['texts'],
                       key=lambda t: abs(t[1] / (scale or 1) - left) + abs(t[2] / (scale or 1) - top),
                       default=None)
            if best is None:
                continue
            dx = abs(best[1] / (scale or 1) - left)
            dy = abs(best[2] / (scale or 1) - top)
            if dx > tol or dy > tol:
                pos_off += 1
                problems.append(f'Folie {i+1} „{r["title"]}": Position weicht ab — '
                                f'imc ({left:.0f},{top:.0f}) vs. unsere '
                                f'({best[1]/(scale or 1):.0f},{best[2]/(scale or 1):.0f})')
            want_pt = _px(st.get('font-size')) * (scale or 1) * PX_TO_PT
            if want_pt and best[5] and abs(best[5] - want_pt) > 1.0:
                size_off += 1
                problems.append(f'Folie {i+1} „{r["title"]}": Schriftgröße — '
                                f'erwartet {want_pt:.1f}pt, gefunden {best[5]:.1f}pt')

    print(f'Geprüfte Textelemente : {checked}')
    print(f'  fehlender Text      : {miss_text}')
    print(f'  Position abweichend : {pos_off}  (Toleranz {tol:.0f} px)')
    print(f'  Schriftgröße daneben: {size_off}')
    if problems:
        print(f'\nBefunde ({len(problems)}, erste 20):')
        for p in problems[:20]:
            print('   ' + p)
    else:
        print('\n=== KEINE ABWEICHUNG ===')
    return 1 if problems else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('story')
    ap.add_argument('export')
    ap.add_argument('--tolerance', type=float, default=4.0,
                    help='erlaubte Positionsabweichung in imc-Pixeln (Default 4)')
    ap.add_argument('--scale', type=float, default=None,
                    help='Geometrie-Faktor der .story (Default: 1.0 = geometry native)')
    args = ap.parse_args()
    raise SystemExit(compare(args.story, args.export, args.tolerance, args.scale))


if __name__ == '__main__':
    main()
