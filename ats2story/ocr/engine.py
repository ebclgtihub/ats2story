#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR-Engine: Bild -> Roh-Textblöcke (Tesseract, gecacht).

Liest den veränderlichen State (TESSERACT_CMD, OCR_TESSDATA, Sprach-Cache)
zur LAUFZEIT aus :mod:`ats2story.ocr.config` — niemals beim Import kopieren.
So wirkt ein Setzen von ``config.TESSERACT_CMD`` (z.B. aus der App im
PyInstaller-Bundle) sofort.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import os
import subprocess
from collections import OrderedDict

from PIL import Image, ImageFilter

from ..security import IMG_PIXEL_MAX
from . import config

_log = logging.getLogger(__name__)

# OCR-Subprozess-Timeout (Sekunden) — hartes Cap gegen hängende Tesseract-Läufe.
# 60 s statt 30: tessdata_best ist deutlich langsamer als tessdata_fast.
_OCR_TIMEOUT = 60

# Seitensegmentierung: psm 3 (volle Layout-Analyse) liefert Block-/Absatz-
# Struktur; psm 6 („ein Textblock") ist das alte Verhalten und dient als
# Fallback-Netz, wenn psm 3 leer bleibt oder schlechte Konfidenz liefert.
_PSM_PRIMARY = 3
_PSM_FALLBACK = 6

# 2x-Upscale (bicubic) vor OCR, wenn die mediane Zeilenhöhe darunter liegt —
# kleine Schrift erkennt Tesseract hochskaliert deutlich besser.
_UPSCALE_MIN_LINE_H = 20
_UPSCALE_FACTOR = 2

# Fett-Heuristik (Strichbreite per Erosion, s. _word_bold): ein Wort gilt als
# fett, wenn seine relative Strichbreite >= KlassenMedian * FACTOR (und
# mindestens Median + DELTA) ist. Verglichen wird je Größenklasse der
# Worthöhe (nicht global) — Überschriften haben absolut dickere Striche.
_BOLD_STROKE_FACTOR = 1.30
_BOLD_STROKE_DELTA = 0.025
# Minimale Wort-Kästchengröße (px), damit die Strichbreite verlässlich ist —
# winzige Krümel liefern verrauschte Werte und dürfen nicht fett flippen.
_BOLD_MIN_AREA = 40
# Mindestanzahl Messungen je Größenklasse; darunter zählt der globale Median.
_BOLD_MIN_CLASS = 3
# Wenn mehr als dieser Anteil der Wörter „fett" wäre, ist die Heuristik
# bedeutungslos (einheitlich schwere Schrift) -> gar nichts fett markieren.
_BOLD_MAX_RATIO = 0.6

# Zeilenanfangs-Marker, die einen NEUEN Absatz/Listenpunkt einleiten
# (Gedankenstrich/Bullet) statt an die Vorzeile angehängt zu werden.
_DASH_BULLETS = ('-', '–', '—', '•', '·', '*')

# Rect-unabhängiger Roh-OCR-Cache: md5(png) -> raw-dict | None.
# NICHT thread-safe: aktuell gibt es keinen parallelen OCR-Pfad (Builder läuft
# sequenziell). Bei künftigem concurrent OCR -> threading.Lock oder lru_cache.
_OCR_RAW_CACHE: dict[str, dict | None] = {}


def _ocr_env() -> dict[str, str]:
    """Prozess-Env für Tesseract (optional eigenes TESSDATA_PREFIX)."""
    env = os.environ.copy()
    if config.OCR_TESSDATA:
        env['TESSDATA_PREFIX'] = config.OCR_TESSDATA
    return env


def _no_window() -> int:
    """``creationflags`` für Subprozesse — unter Windows ohne Konsolenfenster.

    Die App ist windowed (``console=False`` in der PyInstaller-Spec). Ohne
    ``CREATE_NO_WINDOW`` öffnet Windows für JEDEN Tesseract-Aufruf kurz ein
    schwarzes Konsolenfenster — bei einem Kurs mit über tausend Bildern also
    tausendfaches Aufblitzen. Auf macOS/Linux existiert das Flag nicht und der
    Wert ist 0 (= keine Sonderbehandlung).
    """
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def ocr_lang() -> str | None:
    """Tesseract-Sprache: bevorzugt OCR_LANG_PREF, sonst 'eng', sonst None.

    Ergebnis wird in ``config._OCR_LANG_CACHE`` gecacht.
    """
    if config._OCR_LANG_CACHE is not None:
        return config._OCR_LANG_CACHE or None
    try:
        out = subprocess.run([config.TESSERACT_CMD, '--list-langs'], capture_output=True,
                             text=True, timeout=_OCR_TIMEOUT, env=_ocr_env(),
                             creationflags=_no_window()).stdout
        langs = {ln.strip() for ln in out.splitlines()[1:] if ln.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        _log.debug('ocr_lang: --list-langs fehlgeschlagen: %s', exc, exc_info=True)
        langs = set()
    config._OCR_LANG_CACHE = (config.OCR_LANG_PREF if config.OCR_LANG_PREF in langs
                              else ('eng' if 'eng' in langs else ''))
    return config._OCR_LANG_CACHE or None


def _flatten_gray(png_bytes: bytes) -> tuple[Image.Image, Image.Image]:
    """Bild auf weißem Hintergrund flach machen -> (RGBA, Graustufen).

    Raises ValueError, wenn das Bild den Pixel-Cap überschreitet.
    """
    im = Image.open(io.BytesIO(png_bytes))
    if im.width * im.height > IMG_PIXEL_MAX:
        raise ValueError(f'Image too large for OCR: {im.width}x{im.height}')
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return im, bg.convert('L')


def _text_color(rgba: Image.Image) -> str:
    """Dominante dunkle Textfarbe (Mittel der dunkelsten ~20% opaken Pixel)."""
    small = rgba.convert('RGBA')
    small.thumbnail((160, 160))
    px = small.load()
    darks = []
    for y in range(small.height):
        for x in range(small.width):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum < 150:
                darks.append((lum, r, g, b))
    if not darks:
        return '#222222'
    darks.sort(key=lambda t: t[0])
    take = darks[:max(1, len(darks) // 5)]
    r = sum(t[1] for t in take) // len(take)
    g = sum(t[2] for t in take) // len(take)
    b = sum(t[3] for t in take) // len(take)
    return f'#{r:02X}{g:02X}{b:02X}'


def _region_color(rgba: Image.Image, bbox: tuple | None) -> str | None:
    """Schriftfarbe INNERHALB einer Absatz-BBox — auch hell auf dunkel.

    :func:`_text_color` mittelt eine dunkle Farbe über das GANZE Bild und
    verwirft alles ab Luminanz 150; weiße Schrift auf dunklem Grund wurde
    dadurch als ``#222222`` exportiert (unsichtbar) und mehrfarbige Bilder
    bekamen eine Einheitsfarbe. Hier gilt stattdessen: häufigste Luminanz im
    Ausschnitt = Hintergrund, die am weitesten davon entfernten Pixel = Schrift.
    """
    if bbox is None:
        return None
    l, t, r, b = (int(v) for v in bbox)
    if r - l < 2 or b - t < 2:
        return None
    try:
        crop = rgba.convert('RGBA').crop((l, t, r, b))
        if crop.width * crop.height > 400 * 400:
            crop.thumbnail((400, 400))
        buf = crop.tobytes()              # RGBA-Bytes (getdata ist deprecated)
        px = [tuple(buf[i:i + 4]) for i in range(0, len(buf), 4)]
    except Exception as exc:
        _log.debug('_region_color: Ausschnitt %s fehlgeschlagen: %s', bbox, exc, exc_info=True)
        return None

    vis = [(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2], p) for p in px if p[3] >= 128]
    if len(vis) < 8:
        return None
    # Hintergrund = Modus der Luminanz (16er-Klassen), Schrift = die am
    # weitesten entfernten 20% der Pixel.
    hist: dict[int, int] = {}
    for lum, _p in vis:
        hist[int(lum) // 16] = hist.get(int(lum) // 16, 0) + 1
    bg_lum = max(hist.items(), key=lambda kv: kv[1])[0] * 16 + 8
    vis.sort(key=lambda t_: -abs(t_[0] - bg_lum))
    take = vis[:max(1, len(vis) // 10)]
    if abs(take[0][0] - bg_lum) < 40:
        return None                       # kein Kontrast -> kein verlässlicher Wert
    # MEDIAN statt Mittelwert: Kantenglättung erzeugt eine Rampe zum
    # Hintergrund; ein Mittelwert zöge die Farbe dorthin (aus reinem #003366
    # würde ein ausgewaschener Ton).
    def med(idx: int) -> int:
        vals = sorted(p[1][idx] for p in take)
        return vals[len(vals) // 2]

    return f'#{med(0):02X}{med(1):02X}{med(2):02X}'


def _word_bold(gray: Image.Image, left: int, top: int, width: int, height: int) -> float:
    """Relative Strichbreite eines Wort-Kästchens (Strichbreite/Worthöhe), 0..1.

    Erosions-Trick statt roher Pixel-Dichte: der binarisierte Crop wird mit
    ``MaxFilter(3)`` erodiert (dunkle Striche verlieren ~1 px je Seite). Aus
    ``ratio = dunkel_nachher / dunkel_vorher`` folgt die Strichbreite
    ``w ≈ 2 / (1 - ratio)`` px; normiert auf die Worthöhe ist das Maß
    schriftgrößen-unabhängig (fette Wörter haben höhere Werte).
    """
    if width <= 0 or height <= 0:
        return 0.0
    try:
        crop = gray.crop((left, top, left + width, top + height))
        bw = crop.point(lambda v: 0 if v < 128 else 255)
        dark_before = bw.histogram()[0]
        if not dark_before:
            return 0.0
        eroded = bw.filter(ImageFilter.MaxFilter(3))
        dark_after = eroded.histogram()[0]
    except Exception as exc:
        _log.debug('_word_bold: Messung fehlgeschlagen (%s,%s,%s,%s): %s',
                   left, top, width, height, exc, exc_info=True)
        return 0.0
    ratio = dark_after / dark_before
    stroke = 2.0 / (1.0 - ratio) if ratio < 1.0 else float(height)
    return min(1.0, stroke / max(1, height))


def _size_class(h: int) -> int:
    """Größenklasse einer Worthöhe (~25%-Stufen, logarithmisch)."""
    return int(round(math.log(max(1, h), 1.25)))


def _median(vals: list[float]) -> float:
    """Median einer nichtleeren Liste (einfaches mittleres Element)."""
    s = sorted(vals)
    return s[len(s) // 2]


def _mark_bold(gray: Image.Image, rows: list[dict]) -> None:
    """Fett-Flag je Wort setzen (Strichbreiten-Heuristik, größenklassen-relativ).

    Härtungen ggü. dem alten globalen Dichte-Median:
    * Gemessen wird die EROSIONS-Strichbreite (s. ``_word_bold``), normiert
      auf die Worthöhe — schriftgrößen-unabhängig.
    * Verglichen wird je GRÖSSENKLASSE der Worthöhe (Überschriften vs.
      Fließtext getrennt); Klassen mit < ``_BOLD_MIN_CLASS`` Messungen
      fallen auf den globalen Median zurück.
    * Winzige Kästchen (< ``_BOLD_MIN_AREA`` px) liefern verrauschte Werte
      und werden weder gemessen noch fett markiert.
    * Wären mehr als ``_BOLD_MAX_RATIO`` der Wörter fett, ist die Heuristik
      bedeutungslos (durchgängig schwere Schrift) -> gar nichts fett.

    Setzt ``x['stroke']`` und ``x['bold']`` in-place für jedes ``x`` in ``rows``.
    """
    for x in rows:
        area = x['width'] * x['h']
        x['stroke'] = (_word_bold(gray, x['left'], x['top'], x['width'], x['h'])
                       if area >= _BOLD_MIN_AREA else 0.0)

    measured = [x['stroke'] for x in rows if x['stroke'] > 0]
    if not measured:
        for x in rows:
            x['bold'] = False
        return

    global_med = _median(measured)
    classes: dict[int, list[float]] = {}
    for x in rows:
        if x['stroke'] > 0:
            classes.setdefault(_size_class(x['h']), []).append(x['stroke'])

    def bold_cut(h: int) -> float:
        vals = classes.get(_size_class(h), [])
        med = _median(vals) if len(vals) >= _BOLD_MIN_CLASS else global_med
        return max(med * _BOLD_STROKE_FACTOR, med + _BOLD_STROKE_DELTA)

    candidates = [x for x in rows if x['stroke'] > 0 and x['stroke'] >= bold_cut(x['h'])]
    # Bei durchgängig schwerer Schrift (fast alles über dem Cut) ist die
    # Unterscheidung wertlos -> nichts fett markieren.
    if len(candidates) > _BOLD_MAX_RATIO * len(measured):
        for x in rows:
            x['bold'] = False
        return

    cand_ids = {id(x) for x in candidates}
    for x in rows:
        x['bold'] = id(x) in cand_ids


def _run_tesseract(img: Image.Image, lang: str, psm: int) -> list[dict]:
    """Ein Tesseract-TSV-Lauf über ``img`` -> Wort-Rows (conf>=0, nicht leer).

    Row-Keys: block, par, line (TSV-Nummern), left/top/width/h (px), conf, txt.
    """
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    # TSV per PARAMETER anfordern, nicht über den Config-Namen 'tsv': der ist
    # eine Datei in ``tessdata/configs/`` und fehlt in gebündelten tessdata-
    # Verzeichnissen. Tesseract meldet dann nur "read_params_file: Can't open
    # tsv", liefert Klartext — und die TSV-Auswertung fand NULL Wörter, d.h.
    # OCR war im Bundle stillschweigend wirkungslos.
    r = subprocess.run(
        [config.TESSERACT_CMD, 'stdin', 'stdout', '-l', lang, '--oem', '1',
         '--psm', str(psm), '-c', 'tessedit_create_tsv=1'],
        input=buf.getvalue(), capture_output=True, timeout=_OCR_TIMEOUT, env=_ocr_env(),
        creationflags=_no_window())
    tsv = r.stdout.decode('utf-8', 'replace')
    if tsv and not tsv.lstrip().startswith('level\t'):
        _log.warning('OCR: Tesseract lieferte kein TSV (%s ...) — Ausgabe wird verworfen',
                     tsv[:60].replace('\n', ' '))
        return []
    # TSV-Spalten: level0 page1 block2 par3 line4 word5 left6 top7 width8 height9 conf10 text11
    rows: list[dict] = []
    for ln in tsv.splitlines()[1:]:
        c = ln.split('\t')
        if len(c) < 12:
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 0 or not c[11].strip():
            continue
        try:
            left, top, width = int(c[6]), int(c[7]), int(c[8])
        except ValueError:
            left = top = width = 0
        rows.append(dict(block=c[2], par=c[3], line=c[4], left=left, top=top,
                         width=width, h=int(c[9]), conf=conf, txt=c[11]))
    return rows


def _mean_conf(rows: list[dict]) -> float:
    """Mittlere Wort-Konfidenz (0.0 bei leeren Rows)."""
    return (sum(x['conf'] for x in rows) / len(rows)) if rows else 0.0


def _rows_med_h(rows: list[dict]) -> int:
    """Mediane Worthöhe (px) über alle Rows (0, wenn keine messbar)."""
    heights = [x['h'] for x in rows if x['h'] > 0]
    return int(_median(heights)) if heights else 0


def _ocr_raw(png_bytes: bytes) -> dict | None:
    """Rect-unabhängiges OCR eines Bildes (gecacht per md5 + OCR-Optionen).

    -> dict(paras, para_runs, para_texts, med_h, img_w, img_h, conf, chars,
    color) bei Text, sonst None. ``paras`` enthält pro Absatz
    ``dict(runs, text, bbox=(l,t,r,b) in Bild-px, line_h)`` — die Basis für
    positionierte Textboxen. ``para_runs``/``para_texts`` bleiben als flache
    Sichten erhalten (Rückwärtskompatibilität).

    Ablauf: psm 3 (Layout-Analyse); bei kleiner Schrift (mediane Zeilenhöhe
    < ``_UPSCALE_MIN_LINE_H``) 2x-Bicubic-Upscale + erneuter Lauf; bleibt das
    Ergebnis leer oder unter ``OCR_MIN_CONF``, psm-6-Fallback (altes
    Verhalten als Netz). Zählt Fehler in ``config._ocr_errors``.
    """
    key = (hashlib.md5(png_bytes).hexdigest()
           + f':psm{_PSM_PRIMARY}-{_PSM_FALLBACK}:up{_UPSCALE_FACTOR}@{_UPSCALE_MIN_LINE_H}')
    if key in _OCR_RAW_CACHE:
        return _OCR_RAW_CACHE[key]
    lang = ocr_lang()
    res: dict | None = None
    try:
        im_rgba, gray = _flatten_gray(png_bytes)
        rows = _run_tesseract(gray, lang, _PSM_PRIMARY)
        scale = 1.0                       # Faktor Bild-px -> OCR-Koordinaten

        # Kleine Schrift? -> 2x-Upscale (bicubic) und erneut (bessere Erkennung).
        med = _rows_med_h(rows)
        up_px = gray.width * gray.height * _UPSCALE_FACTOR ** 2
        if rows and 0 < med < _UPSCALE_MIN_LINE_H and up_px <= IMG_PIXEL_MAX:
            up = gray.resize((gray.width * _UPSCALE_FACTOR,
                              gray.height * _UPSCALE_FACTOR), Image.BICUBIC)
            rows_up = _run_tesseract(up, lang, _PSM_PRIMARY)
            if rows_up:
                rows, gray = rows_up, up
                scale = float(_UPSCALE_FACTOR)

        # psm-6-Fallback (heutiges Verhalten als Netz) bei leer/schlechter Konfidenz.
        if not rows or _mean_conf(rows) < config.OCR_MIN_CONF:
            rows_fb = _run_tesseract(gray, lang, _PSM_FALLBACK)
            if rows_fb and _mean_conf(rows_fb) > _mean_conf(rows):
                rows = rows_fb

        if rows:
            mean_conf = _mean_conf(rows)
            full = ' '.join(x['txt'] for x in rows)
            if mean_conf >= config.OCR_MIN_CONF and len(full.strip()) >= config.OCR_MIN_CHARS:
                # Fett-Heuristik (Strichbreite per Erosion, größenklassen-
                # relativ). Setzt x['bold'] je Wort.
                _mark_bold(gray, rows)

                # Wörter -> Zeilen -> Absätze; psm 3 nummeriert par/line je
                # BLOCK neu, daher block in beiden Schlüsseln mitführen.
                lines: OrderedDict = OrderedDict()
                for x in rows:
                    lines.setdefault((x['block'], x['par'], x['line']), []).append(x)
                paras: OrderedDict = OrderedDict()
                for (block, par, _line), words in lines.items():
                    paras.setdefault((block, par), []).append(words)

                para_dicts = _build_paragraphs(paras)

                # Schriftfarbe JE ABSATZ aus dem Bildausschnitt (Bezugsbild
                # muss dieselbe Skalierung haben wie die Wort-Boxen).
                ref = im_rgba if gray.size == im_rgba.size else im_rgba.resize(gray.size)
                for p in para_dicts:
                    p['color'] = _region_color(ref, p.get('bbox'))

                if para_dicts:
                    from .imagemask import nontext_ink_ratio
                    res = dict(paras=para_dicts,
                               para_runs=[p['runs'] for p in para_dicts],
                               para_texts=[p['text'] for p in para_dicts],
                               med_h=_rows_med_h(rows),
                               img_w=max(1, gray.width), img_h=max(1, gray.height),
                               conf=round(mean_conf), chars=len(full),
                               scale=scale,
                               nontext=nontext_ink_ratio(
                                   gray, [p['bbox'] for p in para_dicts]),
                               color=_text_color(im_rgba))
    except subprocess.TimeoutExpired as exc:
        _log.debug('_ocr_raw: Tesseract-Timeout: %s', exc, exc_info=True)
        config._ocr_errors += 1
        res = None
    except Exception as exc:
        _log.debug('_ocr_raw: OCR fehlgeschlagen: %s', exc, exc_info=True)
        config._ocr_errors += 1
        res = None
    _OCR_RAW_CACHE[key] = res
    return res


def _append_run(runs: list[tuple[str, bool]], text: str, bold: bool) -> None:
    """Wort an Runs anhängen; benachbarte gleich-formatierte Runs verschmelzen."""
    if runs and runs[-1][1] == bold:
        runs[-1] = (runs[-1][0] + text, bold)
    else:
        runs.append((text, bold))


def _strip_trailing_hyphen(runs: list[tuple[str, bool]]) -> None:
    """Trenn-`-` vom Ende des letzten Runs entfernen (Silbentrennungs-Fix).

    Wird bei aufgelöster Zeilenumbruch-Silbentrennung aufgerufen, damit die
    gerenderten Runs kein lose stehendes „Beispiel-" zeigen. Nachlaufende leere
    Runs (etwa ein Run, der nur aus `-` bestand) werden verworfen.
    """
    while runs and runs[-1][0].endswith('-'):
        text, bold = runs[-1]
        text = text[:-1]
        if text:
            runs[-1] = (text, bold)
            break
        runs.pop()


def _normalize_runs(runs: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Leere Runs entfernen, führendes Leerzeichen des ersten Runs trimmen."""
    out = [(t, b) for t, b in runs if t]
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1])
        out = [(t, b) for t, b in out if t]
    return out


def _is_bullet_line(line_txt: str) -> bool:
    """Zeile beginnt mit Gedankenstrich/Bullet (neuer Listenpunkt/Absatz)?

    Nur echte Aufzählungen: Marker + Leerzeichen + Text (z.B. „– Punkt"),
    NICHT ein Wort wie „-Test" oder ein Datumsbereich „10-12".
    """
    for mark in _DASH_BULLETS:
        if line_txt.startswith(mark) and line_txt[len(mark):len(mark) + 1] == ' ':
            return True
    return False


def _flush_para(out: list[dict], s: str, runs: list[tuple[str, bool]],
                words: list[dict]) -> None:
    """Einen fertigen Absatz (Text + Runs + BBox aus Wort-Boxen) anhängen."""
    if not s.strip():
        return
    boxed = [w for w in words if w['width'] > 0 and w['h'] > 0]
    if boxed:
        bbox = (min(w['left'] for w in boxed), min(w['top'] for w in boxed),
                max(w['left'] + w['width'] for w in boxed),
                max(w['top'] + w['h'] for w in boxed))
        line_h = int(_median([w['h'] for w in boxed]))
    else:
        bbox = None
        line_h = 0
    out.append(dict(text=s.strip(),
                    runs=_normalize_runs(runs) or [(s.strip(), False)],
                    bbox=bbox, line_h=line_h))


def _build_paragraphs(paras: 'OrderedDict') -> list[dict]:
    """Zeilen je OCR-Absatz -> Liste von Absatz-Dicts.

    Je Absatz: ``dict(text, runs, bbox=(l,t,r,b) in Bild-px | None, line_h)``.
    Die BBox wird aus den Wort-Boxen (min/max) aggregiert, ``line_h`` ist der
    Median der Worthöhen des Absatzes.

    Regeln:
    * Weiche Bild-Zeilenumbrüche werden zu Leerzeichen zusammengezogen.
    * Silbentrennung am Zeilenende (``…-`` + kleingeschriebene Folgezeile) wird
      in Text UND Runs aufgelöst (T1).
    * Zeilen, die mit Gedankenstrich/Bullet beginnen, starten einen NEUEN Absatz
      statt an die Vorzeile angehängt zu werden (T2 — Aufzählungen erhalten).
    """
    out: list[dict] = []

    for _key, line_words in paras.items():
        s = ''
        runs: list[tuple[str, bool]] = []
        acc_words: list[dict] = []
        started = False  # ob im aktuellen (Teil-)Absatz schon Text steht
        for words in line_words:
            line_txt = ' '.join(w['txt'] for w in words).strip()
            if not line_txt:
                continue

            # Bullet-Zeile -> laufenden Absatz abschließen, neuen beginnen.
            if started and _is_bullet_line(line_txt):
                _flush_para(out, s, runs, acc_words)
                s, runs, acc_words, started = '', [], [], False

            # Silbentrennung am Zeilenende auflösen (Text UND Runs, T1).
            dehyphen = (started and s.endswith('-') and len(s) > 1
                        and line_txt[:1].islower())
            if not started:
                s = line_txt
            elif dehyphen:
                s = s[:-1] + line_txt
            else:
                s = s + ' ' + line_txt

            for wi, w in enumerate(words):
                first_of_line = wi == 0
                if not started and first_of_line:
                    sep = ''
                elif dehyphen and first_of_line:
                    _strip_trailing_hyphen(runs)
                    sep = ''
                else:
                    sep = ' '
                _append_run(runs, sep + w['txt'], bool(w.get('bold')))
            acc_words.extend(words)
            started = True

        _flush_para(out, s, runs, acc_words)

    return out
