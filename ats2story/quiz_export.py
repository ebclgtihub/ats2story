#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quizfragen als Articulate-Importdatei (Storyline 360).

Storyline kann Fragen aus einer Excel-Tabelle oder Textdatei importieren und
daraus **echte Quizfolien** bauen — mit Auswertung, Feedback und Punkten. Das
ist der bessere Weg als unser Textbox-Ersatz: dort steht die Frage nur da, hier
wird sie in Storyline zu einer bedienbaren Frage.

Die Fragen liegen im Kurs nicht als Folien, sondern im ``<vault>``-Depot als
``.ati``-Dateien mit den Interaktionselementen — genau die Daten, die dieser
Konverter ohnehin liest.

Format laut Articulate-Dokumentation („Storyline 360: Fragen aus Excel-Tabellen
und Textdateien importieren"):

* Feldreihenfolge: **Fragetyp · Punkte · Fragetext · Antwortoptionen**
* Typkürzel u.a. ``TF`` (Wahr/Falsch), ``MC`` (Multiple Choice),
  ``MR`` (Mehrfachantwort), ``FIB`` (Lückentext), ``SD`` (Reihenfolge per
  Drag&Drop)
* richtige Antworten mit vorangestelltem ``*``
* bis zu 10 Optionen je Frage; bei Reihenfolgefragen in der richtigen Folge
* ``//`` leitet einen Kommentar ein, der beim Import ignoriert wird
* Punkte zwischen -1000 und 1000

Erzeugt werden zwei Dateien: eine ``.xlsx`` (das von Articulate klar
spezifizierte Format) und eine ``.txt`` als Rückfallebene.
"""
from __future__ import annotations

import html
import re
import zipfile

#: imc-Interaktionstyp -> Articulate-Typkürzel.
_TYPE = {'single': 'MC', 'multiple': 'MR', 'textgap': 'FIB', 'draganddrop': 'SD'}

#: Punkte je Frage. Articulate verlangt für benotete Fragen einen Wert.
DEFAULT_POINTS = 10

#: Articulate nimmt höchstens 10 Antwortoptionen je Frage.
MAX_CHOICES = 10

#: Ja/Nein-Paare, die als Wahr/Falsch-Frage (TF) durchgehen. Storyline erwartet
#: dort genau zwei Optionen; der Importer akzeptiert die Beschriftungen des
#: Kurses.
_TRUE_FALSE = ({'richtig', 'falsch'}, {'wahr', 'falsch'}, {'true', 'false'},
               {'ja', 'nein'}, {'prawda', 'fałsz'})


def _plain(rich: str | None) -> str:
    """imc-richText -> Klartext (Markup raus, Whitespace normalisiert)."""
    txt = re.sub(r'<[^>]+>', ' ', html.unescape(rich or ''))
    return re.sub(r'\s+', ' ', txt).strip()


def _question_text(texts: list[str], exclude: str = '') -> str:
    """Der längste Text der Folie ist die Frage.

    Auf einer imc-Frageseite stehen neben der Frage nur die Kopfzeile (der
    Name der Übung) und ggf. Nummern der Ablageziele. Die Frage ist zuverlässig
    der längste Textblock; die Kopfzeile wird zusätzlich ausgeschlossen.
    """
    cands = [t for t in texts if t and t.strip() and t.strip() != exclude.strip()]
    return max(cands, key=len) if cands else ''


def question_from_slide(name: str, items: list, scene: str = '') -> dict | None:
    """Eine Quizfolie -> Frage-dict, oder None wenn keine Interaktion drin ist.

    ``items`` ist das Ergebnis von :func:`ats2story.ats_reader.slide_content`.
    """
    choices = [p for _l, k, p in items if k == 'choices']
    if not choices:
        return None
    ch = choices[0]
    kind = ch.get('kind')
    if kind not in _TYPE:
        return None

    texts = [_plain(p['rich']) for _l, k, p in items if k == 'text']
    text = ch.get('prompt') or _question_text(texts, exclude=scene) or name
    options = list(ch.get('options') or ())
    if not options:
        return None

    qtype = _TYPE[kind]
    if qtype == 'MC' and len(options) == 2:
        labels = {o[0].strip().rstrip('.').casefold() for o in options}
        if labels in _TRUE_FALSE:
            qtype = 'TF'
    return dict(type=qtype, points=DEFAULT_POINTS, text=text,
                options=options[:MAX_CHOICES], slide=name, scene=scene)


def collect_questions(scenes: list[dict], slide_content) -> list[dict]:
    """Alle Quizfolien eines Kurses -> Fragenliste (in Kursreihenfolge)."""
    out = []
    for sc in scenes:
        for s in sc.get('slides', ()):
            if not s.get('quiz') or not s.get('ata'):
                continue
            try:
                items, _audio = slide_content(s['ata'])
            except Exception:
                continue
            q = question_from_slide(s.get('name', 'Frage'), items, sc.get('name', ''))
            if q:
                out.append(q)
    return out


def _row(q: dict) -> list[str]:
    """Frage -> Zeile in Articulates Feldreihenfolge."""
    row = [q['type'], str(q['points']), q['text']]
    for text, correct in q['options']:
        # Bei Reihenfolgefragen (SD) zählt die Folge, kein Sternchen.
        row.append(('*' if correct and q['type'] != 'SD' else '') + text)
    return row


def write_text(questions: list[dict], path: str) -> int:
    """Textdatei schreiben — jedes Feld in einer eigenen Zeile, Leerzeile trennt.

    Articulate: „Geben Sie jedes Element in einer neuen Zeile ein."
    """
    lines = ['// Erzeugt von ats2story — Import in Storyline 360:',
             '// Datei > Import > Fragen aus Datei', '']
    for q in questions:
        lines.append(f'// {q["scene"]} — {q["slide"]}')
        lines.extend(_row(q))
        lines.append('')
    with open(path, 'w', encoding='utf-8-sig', newline='\r\n') as fh:
        fh.write('\n'.join(lines))
    return len(questions)


# --------------------------------------------------------------------------
# Minimales XLSX — bewusst ohne Fremdbibliothek: die App wird gebündelt
# ausgeliefert, und eine Tabellenbibliothek nur für vier Spalten wäre unnötiger
# Ballast. Ein XLSX ist ein ZIP aus wenigen XML-Teilen; dieses Projekt schreibt
# mit dem .story-Paket ohnehin ein deutlich komplexeres OPC-Format.
# --------------------------------------------------------------------------
_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
       '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Target="xl/workbook.xml" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
         '</Relationships>')
_WB = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
       '<sheets><sheet name="Fragen" sheetId="1" r:id="rId1"/></sheets></workbook>')
_WB_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            '</Relationships>')


def _col(i: int) -> str:
    """0-basierte Spaltennummer -> Excel-Buchstabe (A, B, … Z, AA …)."""
    name = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def _sheet(rows: list[list[str]]) -> str:
    """Arbeitsblatt-XML mit Inline-Strings (spart die sharedStrings-Tabelle)."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetData>']
    for r, row in enumerate(rows, start=1):
        out.append(f'<row r="{r}">')
        for c, val in enumerate(row):
            if val is None or val == '':
                continue
            esc = html.escape(str(val), quote=False)
            out.append(f'<c r="{_col(c)}{r}" t="inlineStr"><is><t xml:space="preserve">'
                       f'{esc}</t></is></c>')
        out.append('</row>')
    out.append('</sheetData></worksheet>')
    return ''.join(out)


def write_xlsx(questions: list[dict], path: str) -> int:
    """Excel-Tabelle im Articulate-Importformat schreiben."""
    rows = [['// Fragetyp', '// Punkte', '// Fragetext', '// Antwortoptionen']]
    rows.extend(_row(q) for q in questions)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CT)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('xl/workbook.xml', _WB)
        z.writestr('xl/_rels/workbook.xml.rels', _WB_RELS)
        z.writestr('xl/worksheets/sheet1.xml', _sheet(rows))
    return len(questions)
