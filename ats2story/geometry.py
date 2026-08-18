#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geometrie (imc-Canvas -> Storyline-Canvas) und XML-Fragment-Helfer.

imc Content Studio rendert je nach Geräteprofil auf unterschiedliche Canvas-
Größen (beobachtet: 1024x748 und 950x630), Storyline auf 1280x720.
:class:`Geometry` bündelt Canvas + Modus und liefert sowohl die Rect- als auch
die Schriftgrößen-Umrechnung; ``fit_rect``/``fill_rect``/``native_rect``
bleiben als Modul-Funktionen für den Default-Canvas erhalten.

``fit`` skaliert letterbox-zentriert (mit Seitenbalken), ``fill`` crop-to-fill
(ohne Balken, Überstände werden abgeschnitten), ``native`` übernimmt die
imc-Koordinaten 1:1 (die Story-Size wird dann auf den Canvas gestellt).
"""
from __future__ import annotations

from typing import Literal

ATS_W, ATS_H = 1024, 748          # imc-Default-Canvas (Fallback ohne Erkennung)
SLD_W, SLD_H = 1280, 720          # Storyline Canvas (aus Vorlage)
NATIVE_W, NATIVE_H = 1024, 748    # 'native': Story-Size = imc-Canvas (keine Skalierung)

#: px -> pt (72/96). imc-Schriftgrößen sind PIXEL auf dem imc-Canvas,
#: Storyline speichert PUNKT — ohne diesen Faktor erscheint aller Text ~1/3
#: zu groß und läuft aus den Textboxen.
PX_TO_PT = 0.75

#: Schriftgrößen-Grenzen nach der Umrechnung (Schutz gegen Ausreißer).
MIN_PT, MAX_PT = 4.0, 200.0

Mode = Literal['fit', 'fill', 'native']

# ---- fit (letterbox) -------------------------------------------------------
_FIT_SCALE = min(SLD_W / ATS_W, SLD_H / ATS_H)
_FIT_OFFX = (SLD_W - ATS_W * _FIT_SCALE) / 2
_FIT_OFFY = (SLD_H - ATS_H * _FIT_SCALE) / 2

# ---- fill (crop-to-fill) ---------------------------------------------------
_FILL_SCALE = max(SLD_W / ATS_W, SLD_H / ATS_H)
_FILL_OFFX = (SLD_W - ATS_W * _FILL_SCALE) / 2
_FILL_OFFY = (SLD_H - ATS_H * _FILL_SCALE) / 2

Rect = tuple[float, float, float, float]


def fit_rect(x: float, y: float, w: float, h: float) -> Rect:
    """imc-Rect (1024x748) -> Storyline-loc (l,t,r,b), letterbox-zentriert.

    Skaliert so, dass der gesamte imc-Canvas sichtbar bleibt (mit
    Seitenbalken). Garantiert keine abgeschnittenen Inhalte.
    """
    return (x * _FIT_SCALE + _FIT_OFFX, y * _FIT_SCALE + _FIT_OFFY,
            (x + w) * _FIT_SCALE + _FIT_OFFX, (y + h) * _FIT_SCALE + _FIT_OFFY)


def fill_rect(x: float, y: float, w: float, h: float) -> Rect:
    """imc-Rect (1024x748) -> Storyline-loc (l,t,r,b), crop-to-fill.

    Skaliert BREITEN-getrieben (``_FILL_SCALE = max(1280/1024, 720/748) =
    1.25``): die volle Folienbreite wird ohne Seitenbalken gefüllt. Der
    skalierte imc-Canvas (748*1.25 = 935 px) ist höher als die Folie (720 px),
    also ragen OBERE und UNTERE Überstände über den Folienrand hinaus
    (~107,5 px je Seite, ~11,5%) und werden in Storyline abgeschnitten.
    Beispiel: ``fill_rect(0,0,1024,748) = (0.0, -107.5, 1280.0, 827.5)``.
    ACHTUNG: Inhalte am OBEREN/UNTEREN imc-Rand können dadurch teilweise
    verschwinden (links/rechts bleibt vollständig).
    """
    return (x * _FILL_SCALE + _FILL_OFFX, y * _FILL_SCALE + _FILL_OFFY,
            (x + w) * _FILL_SCALE + _FILL_OFFX, (y + h) * _FILL_SCALE + _FILL_OFFY)


def native_rect(x: float, y: float, w: float, h: float) -> Rect:
    """imc-Rect (1024x748) -> Storyline-loc (l,t,r,b), IDENTITÄT.

    Für ``geometry='native'``: die Story-Size wird per
    :func:`ats2story.story_writer.set_story_size` auf den imc-Canvas gesetzt,
    imc-Koordinaten werden also 1:1 übernommen (kein Skalieren, keine
    Balken, kein Crop). Storyline reskaliert zur Laufzeit selbst.
    """
    return (x, y, x + w, y + h)


class Geometry:
    """Canvas-abhängige Umrechnung imc -> Storyline (Rects UND Schriftgrößen).

    Instanzen sind aufrufbar (``geom(x, y, w, h) -> Rect``) und können damit
    überall dort eingesetzt werden, wo bisher ``fit_rect``/``fill_rect``/
    ``native_rect`` als ``rect_transform`` durchgereicht wurden.

    ``ats_w``/``ats_h`` sind der ERKANNTE imc-Canvas des Kurses (siehe
    :func:`ats2story.ats_reader.detect_canvas`) — fest verdrahtete 1024x748
    verschieben und skalieren sonst jeden Kurs mit abweichendem Geräteprofil.
    """

    def __init__(self, mode: Mode = 'fit', ats_w: int = ATS_W, ats_h: int = ATS_H,
                 sld_w: int = SLD_W, sld_h: int = SLD_H) -> None:
        self.mode: Mode = mode if mode in ('fit', 'fill', 'native') else 'fit'
        self.ats_w = max(1, int(ats_w))
        self.ats_h = max(1, int(ats_h))
        if self.mode == 'native':
            # Story-Size = imc-Canvas -> Identität.
            self.story_w, self.story_h = self.ats_w, self.ats_h
            self.scale = 1.0
            self.off_x = self.off_y = 0.0
        else:
            self.story_w, self.story_h = int(sld_w), int(sld_h)
            pick = min if self.mode == 'fit' else max
            self.scale = pick(self.story_w / self.ats_w, self.story_h / self.ats_h)
            self.off_x = (self.story_w - self.ats_w * self.scale) / 2
            self.off_y = (self.story_h - self.ats_h * self.scale) / 2

    def __call__(self, x: float, y: float, w: float, h: float) -> Rect:
        """imc-Rect (x,y,w,h) -> Storyline-loc (l,t,r,b)."""
        return (x * self.scale + self.off_x, y * self.scale + self.off_y,
                (x + w) * self.scale + self.off_x, (y + h) * self.scale + self.off_y)

    def font_pt(self, px: float | str | None, default_px: float = 18.0) -> float:
        """imc-Schriftgröße (px auf dem imc-Canvas) -> Storyline-Punkt.

        Berücksichtigt die Canvas-Skalierung: eine 18-px-Schrift auf einem
        1024er Canvas ist im 1280er Storyline-fit (Faktor 0,96) 17,3 px hoch
        = 13 pt. Ohne diese Umrechnung landet „18" als 18 pt (= 24 px) in der
        .story — Text bricht um und läuft aus der Box.
        """
        try:
            val = float(str(px).strip().rstrip('px').strip() or default_px)
        except (TypeError, ValueError):
            val = default_px
        if val <= 0:
            val = default_px
        return round(min(MAX_PT, max(MIN_PT, val * self.scale * PX_TO_PT)), 1)

    def __repr__(self) -> str:  # pragma: no cover - nur Diagnose
        return (f'Geometry(mode={self.mode!r}, ats={self.ats_w}x{self.ats_h}, '
                f'story={self.story_w}x{self.story_h}, scale={self.scale:.4f})')


def extract_element(s: str, start: int, tag: str) -> str | None:
    """Tag-balanciertes Element ab ``start`` (zeigt auf '<tag').

    Achtet auf verschachtelte gleichnamige Tags (z.B. ``<pic>`` in
    ``<picFormat>``), Präfix-Kollisionen (``<picFormat>``) und self-closing.
    """
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


def find_first(s: str, tagopen: str) -> int:
    """Index des ersten echten Vorkommens von z.B. '<pic' (als '<pic ' oder '<pic>')."""
    i = 0
    while True:
        i = s.find(tagopen, i)
        if i == -1:
            return -1
        nxt = i + len(tagopen)
        if nxt < len(s) and s[nxt] in ' >\t\n':
            return i
        i = nxt
