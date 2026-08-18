#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parst den Inhalt einer einzelnen .ata-Folie (Bilder, Texte, Audio)."""
from __future__ import annotations

import io
import zipfile

from ..security import safe_zip_read
from ._ns import ET, NS

Rect = tuple[float, float, float, float]
SlideItem = tuple[int, str, dict]  # (layer, kind, payload)


def cp(e, name: str):
    """complexproperty mit Namen ``name`` direkt unter ``e`` finden."""
    for c in e.findall(NS + 'complexproperty'):
        if c.get('name') == name:
            return c
    return None


def rect_of(e) -> Rect | None:
    """Liest das ``rect``-complexproperty eines Elements -> (x, y, w, h)."""
    r = cp(e, 'rect')
    if r is None:
        return None
    rr = r.find(NS + 'rect')
    if rr is None:
        return None
    return (float(rr.get('x', 0)), float(rr.get('y', 0)),
            float(rr.get('width', 0)), float(rr.get('height', 0)))


def is_disabled(e) -> bool:
    """imc-Element ausgeblendet? (``disabled="true"``)

    Ausgeblendete Elemente sind im imc-Player unsichtbar; ohne diese Prüfung
    landeten sie sichtbar in der .story.
    """
    return (e.get('disabled') or '').strip().lower() == 'true'


def _argb_to_hex(val: str | None) -> str | None:
    """imc-Farbe (``#aarrggbb`` oder ``#rrggbb``) -> ``#rrggbb`` (None bei transparent)."""
    if not val:
        return None
    v = val.strip().lstrip('#')
    if len(v) == 8:                      # AARRGGBB
        if int(v[:2], 16) == 0:
            return None                  # voll transparent
        v = v[2:]
    if len(v) != 6:
        return None
    return '#' + v.upper()


def fill_of(e) -> str | None:
    """Füllfarbe eines Elements (``complexproperty name="fill"``) oder None.

    ``style="0"`` bedeutet „keine Füllung"; jede andere Angabe liefert die
    Farbe des enthaltenen ``<color>``.
    """
    f = cp(e, 'fill')
    if f is None:
        return None
    ff = f.find(NS + 'fill')
    if ff is None or (ff.get('style') or '0') == '0':
        return None
    col = ff.find(NS + 'color')
    return _argb_to_hex(col.get('color') if col is not None else None)


def stroke_of(e) -> tuple[str, float] | None:
    """Rahmen eines Elements -> ``(farbe, breite)`` oder None (``style="0"``)."""
    s = cp(e, 'stroke')
    if s is None:
        return None
    ss = s.find(NS + 'stroke')
    if ss is None or (ss.get('style') or '0') == '0':
        return None
    fill = ss.find(NS + 'fill')
    col = fill.find(NS + 'color') if fill is not None else None
    hexcol = _argb_to_hex(col.get('color') if col is not None else None)
    if not hexcol:
        return None
    try:
        width = float(ss.get('width', 1) or 1)
    except (TypeError, ValueError):
        width = 1.0
    return (hexcol, width)


def _num(e, attr: str, default: float) -> float:
    """Numerisches Attribut robust lesen."""
    try:
        return float(e.get(attr, default))
    except (TypeError, ValueError):
        return default


#: Plausibilitätsgrenze der imc-Foliendauer (1 Stunde in Zehntelsekunden) —
#: schützt vor Ausreißern, die sonst eine absurd lange Storyline-Folie ergäben.
_MAX_DURATION_TENTHS = 36000


def slide_duration_ms(ata_bytes: bytes) -> int:
    """``document@duration`` einer .ata in Millisekunden (0, wenn unbrauchbar).

    Die Einheit ist empirisch bestimmt: über die 11 Folien des PL-Kurses
    verhält sich die Länge der hinterlegten Sprecheraufnahme zum Attribut wie
    100,7 : 1 — das Attribut zählt also **Zehntelsekunden**.

    Relevant vor allem für Folien OHNE Audio: für die gab es bisher nur die
    pauschale Mindestdauer, obwohl imc die echte Standzeit mitliefert.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(ata_bytes)) as ata:
            root = ET.fromstring(safe_zip_read(ata, 'document/document.xml'))
        tenths = float(root.get('duration') or 0)
    except Exception:
        return 0
    if not (0 < tenths <= _MAX_DURATION_TENTHS):
        return 0
    return int(round(tenths * 100))


#: imc-Interaktionstypen -> Kurzform. Quizfolien liegen als ``.ati`` im Kurs und
#: benutzen ansonsten DASSELBE Schema wie ``.ata`` (image/text/rect), lassen sich
#: also mit demselben Parser lesen.
_INTERACTION_KINDS = {
    'singlechoiceinteraction': 'single',
    'multiplechoiceinteraction': 'multiple',
    'draganddropinteraction': 'draganddrop',
    'textgapinteraction': 'textgap',
}


def _point_of(e) -> tuple[float, float] | None:
    """``complexproperty name="position"`` -> (x, y)."""
    p = cp(e, 'position')
    pt = p.find(NS + 'point') if p is not None else None
    if pt is None:
        return None
    try:
        return (float(pt.get('x', 0)), float(pt.get('y', 0)))
    except (TypeError, ValueError):
        return None


def _options_of(e, kind: str) -> list[tuple[str, bool]]:
    """Antwortoptionen einer Interaktion -> ``[(text, ist_richtig), ...]``."""
    out: list[tuple[str, bool]] = []
    if kind == 'single':
        try:
            correct = int(float(e.get('correctIndex', -1)))
        except (TypeError, ValueError):
            correct = -1
        for i, c in enumerate(e.findall(NS + 'singlechoice')):
            out.append((c.get('text') or '', i == correct))
    elif kind == 'multiple':
        for c in e.findall(NS + 'multiplechoice'):
            out.append((c.get('text') or '', (c.get('checked') or '') == 'true'))
    elif kind == 'draganddrop':
        # Die LÖSUNG steckt in den Ablagezielen: jedes <droptarget> verweist per
        # <dragsourcereference> auf die richtige Quelle. Die Reihenfolge ergibt
        # sich aus der Position der Ziele auf der Folie (oben nach unten, dann
        # links nach rechts) — im Beispielkurs liefert das exakt die inhaltlich
        # richtige Abfolge. Die <dragsource>-Reihenfolge ist dagegen nur die
        # (gemischte) Anzeigereihenfolge und taugt NICHT als Lösung.
        # Ohne referenceId (theoretisch möglich) bekommt jede Quelle einen
        # eigenen Ersatzschlüssel — sonst fielen mehrere zu einem Eintrag
        # zusammen und Beschriftungen gingen verloren.
        by_ref: dict = {}
        for i, c in enumerate(e.findall(NS + 'dragsource')):
            by_ref[c.get('referenceId') or f'#{i}'] = (c.get('text') or '')
        targets = []
        for t in e.findall(NS + 'droptarget'):
            ref = t.find(NS + 'dragsourcereference')
            if ref is None:
                continue
            text = by_ref.pop(ref.get('referenceId'), None)
            if text:
                targets.append((_point_of(t) or (0.0, 0.0), text))
        # Ziel-Position ist (x, y) -> nach y, dann x sortieren.
        for _pos, text in sorted(targets, key=lambda it: (it[0][1], it[0][0])):
            out.append((text, True))          # bei Reihenfolgefragen zählt die Folge
        # Quellen ohne Ziel (Ablenker) hinten anhängen, damit nichts wegfällt.
        for text in by_ref.values():
            out.append((text, False))
    elif kind == 'textgap':
        for c in e.findall(NS + 'textgap'):
            out.append((c.get('selectedAnswer') or '', True))
    return [(t.strip(), ok) for t, ok in out if t.strip()]


def slide_content(ata_bytes: bytes) -> tuple[list[SlideItem], dict | None]:
    """Inhalt einer .ata-Folie: images, texts, audio-Pfad — in Layer-Reihenfolge.

    Gibt ``(items, audio)`` zurück. ``items`` ist eine nach z-Order (layer)
    sortierte Liste von ``(layer, kind, payload)``. ``audio`` ist ein dict
    ``{bytes, name}`` oder ``None``.
    """
    with zipfile.ZipFile(io.BytesIO(ata_bytes)) as ata:
        names = set(ata.namelist())
        root = ET.fromstring(safe_zip_read(ata, 'document/document.xml'))
        items: list[SlideItem] = []
        audio: dict | None = None
        for e in root.iter():
            tag = e.tag.replace(NS, '')
            if tag in ('image', 'text', 'audiotrack') and is_disabled(e):
                continue                # im imc-Player ausgeblendet
            if tag == 'image':
                r = rect_of(e)
                res = cp(e, 'image')
                res = res.find(NS + 'resource') if res is not None else None
                if r is None or res is None:
                    continue
                path = res.get('path')
                if not path or path not in names:
                    continue
                try:
                    raw = safe_zip_read(ata, path)
                except ValueError:
                    continue  # zip-slip or bomb — skip silently
                items.append((int(_num(e, 'layer', 0)), 'image', dict(
                    rect=r, name=e.get('name') or 'Bild',
                    opacity=_num(e, 'opacity', 100),
                    rotation=_num(e, 'rotation', 0),
                    bytes=raw)))
            elif tag == 'text':
                rt = e.get('richText')
                r = rect_of(e)
                if not rt or r is None:
                    continue
                items.append((int(_num(e, 'layer', 0)), 'text', dict(
                    rect=r, elem=e, rich=rt,
                    align=e.get('textAlign', 'left'),
                    opacity=_num(e, 'opacity', 100),
                    rotation=_num(e, 'rotation', 0),
                    line_height=_num(e, 'lineHeight', 100),
                    fill=fill_of(e), stroke=stroke_of(e),
                    name=e.get('name') or 'Text')))
            elif tag in _INTERACTION_KINDS:
                if is_disabled(e):
                    continue
                kind = _INTERACTION_KINDS[tag]
                opts = _options_of(e, kind)
                if not opts:
                    continue
                pos = _point_of(e) or (0.0, 0.0)
                items.append((int(_num(e, 'layer', 0)), 'choices', dict(
                    rect=(pos[0], pos[1], _num(e, 'width', 600), _num(e, 'height', 200)),
                    kind=kind, options=opts,
                    # ``fontSize="-1"`` heißt „Player-Vorgabe"; 61 der 72
                    # Interaktionen nutzen das, 11 setzen 18–27 px.
                    font_px=_num(e, 'fontSize', -1),
                    prompt=(e.get('text') or '').strip(),
                    name=e.get('name') or 'Antworten')))
            elif tag == 'audiotrack':
                au = e.find(NS + 'audio')
                res = cp(au, 'audio') if au is not None else None
                res = res.find(NS + 'resource') if res is not None else None
                if res is not None:
                    p = res.get('path')
                    if p and p in names:
                        try:
                            audio = dict(bytes=safe_zip_read(ata, p),
                                         name=res.get('originalName') or 'Audio')
                        except ValueError:
                            pass  # zip-slip or bomb — skip audio
        items.sort(key=lambda it: it[0])    # nach Layer (z-Order)
        return items, audio
