#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fragen aus dem imc-Depot als echte Storyline-Fragefolien in einer Fragenbank.

Storyline-Fragefolien lassen sich nicht sinnvoll aus dem Nichts schreiben: eine
einzige Frage ist rund 65 KB XML mit Rückmelde-Ebenen, Absenden-Auslöser,
Bewertung und Verweisen auf Layout und Master. Dieses Modul arbeitet deshalb
mit ECHTEN, in Storyline angelegten Fragen als Vorlage
(``assets/quizbank.story`` — eine Beispieldatei ohne Kursinhalte) und tauscht
darin nur aus, was sich von Frage zu Frage unterscheidet: Fragetext,
Antworttexte, welche Antwort richtig ist und wie viele Antworten es gibt.

Zwei Eigenheiten des Formats machen das überhaupt möglich:

* Alle Antwortzeilen tragen dieselbe Position (``loc l=0 t=0 r=1728 b=68``) —
  Storyline setzt sie selbst untereinander. Eine Zeile hinzuzufügen heißt also
  kopieren, nicht rechnen.
* Welche Antworten zu einer Frage gehören, steht als GUID-Liste im
  ``childLst`` der Interaktion. Die Kopie muss dort nur eingetragen werden.

Nicht abgedeckt: Lückentext. Die Beispieldatei hat dort keine hinterlegte
Lösung, also lässt sich auch nicht ableiten, wohin eine gehört. Solche Fragen
bleiben der Importdatei vorbehalten (:mod:`ats2story.quiz_export`).
"""
from __future__ import annotations

import html
import os
import re
import zipfile

from .geometry import extract_element
from .richtext.formatter import fmt_document
from .guid import GUID_RE, ZERO, newg, relid_from_guid

#: Vorlagendatei — liegt neben dem Storyline-Grundgerüst.
ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'quizbank.story')

#: Fragetyp -> (Vorlagenfolie, Tag der Interaktion, Tag einer Antwortzeile).
#: Nur Typen, deren Vorlage vollständig ausgefüllt ist.
TEMPLATES = {
    # Wahr/Falsch nutzt die Vorlage der EINFACHAUSWAHL: die Wahr/Falsch-Folie
    # der Beispieldatei hat keinen ausgefüllten Titelrahmen, nur Storylines
    # leeren Platzhalter — der Fragetext hätte dort nirgends hingekonnt. Mit der
    # Einfachauswahl behalten die Antworten ausserdem den imc-Wortlaut
    # („Richtig." / „Falsch.") statt zu „True"/„False" zu werden.
    'TF': ('story/slides/slide3.xml', 'multiChoiceIntr', 'radio'),
    'MC': ('story/slides/slide3.xml', 'multiChoiceIntr', 'radio'),
    'MR': ('story/slides/slide4.xml', 'multiRespIntr', 'checkBox'),
    'SD': ('story/slides/slide9.xml', 'seqDragDropIntr', 'seqDragDropItem'),
}

#: Fragetext der Vorlage (Titel-Textrahmen) je Typ.
TITLES = {
    'TF': 'Multiple Choice',
    'MC': 'Multiple Choice',
    'MR': 'Multiple Response',
    'SD': 'Sequence Drag and Drop',
}

#: Typen mit fest vorgegebenen Antworttexten (derzeit keiner — Wahr/Falsch
#: läuft über die Einfachauswahl und behält damit den imc-Wortlaut).
FIXED_CHOICES: set[str] = set()

#: Die Vorlage rechnet in 1920x1080. Der Fragerahmen ist dort ein einzeiliger
#: Streifen (44..122), gedacht für einen kurzen Titel wie „Multiple Choice".
#: imc-Fragen sind aber ganze Aufgabenstellungen — im Median 121 bis 167
#: Zeichen, im längsten Fall 618. In den Streifen gequetscht schrumpft
#: Storyline sie auf Unleserlichkeit. Der Rahmen wächst deshalb mit.
_TITLE_TOP = 44
_TITLE_MIN_BOTTOM = 122
_TITLE_MAX_BOTTOM = 520
_LINE_H = 44                  #: Zeilenhöhe bei der Titelschrift (18,5 pt)
_CHARS_PER_LINE = 95          #: Zeichen, die bei voller Breite in eine Zeile passen
_INTR_GAP = 34                #: Abstand zwischen Frage und erster Antwort
_INTR_BOTTOM = 1004

#: Schriftgrößen der Vorlage (``<resize fontSz>``): Frage 18,5 pt, Antwort 12 pt.
DEFAULT_TITLE_PT = 18.5
DEFAULT_CHOICE_PT = 12.0


def _title_bottom(text: str, pt: float) -> int:
    """Unterkante des Fragerahmens — so hoch, wie der Text Zeilen braucht."""
    per_line = max(20, int(_CHARS_PER_LINE * DEFAULT_TITLE_PT / max(1.0, pt)))
    lines = max(1, -(-len(text) // per_line))
    line_h = _LINE_H * pt / DEFAULT_TITLE_PT
    return int(min(_TITLE_MAX_BOTTOM, max(_TITLE_MIN_BOTTOM, _TITLE_TOP + lines * line_h)))


def _set_loc(frag: str, top: float, bottom: float) -> str:
    """Ober- und Unterkante einer Form setzen (linke/rechte bleiben)."""
    def repl(m):
        return re.sub(r't="[-\d.]+"', f't="{top:.0f}"',
                      re.sub(r'b="[-\d.]+"', f'b="{bottom:.0f}"', m.group(0)))
    return re.sub(r'<loc\b[^>]*/>', repl, frag, count=1)


def _wrap_inside(frag: str, tag: str) -> str:
    """Umbruch einschalten und Text im Rahmen halten.

    Die Vorlage steht auf ``wrap="none"``: gedacht für den kurzen Titel
    „Multiple Choice", der nie umbricht. Eine imc-Aufgabenstellung lief damit
    einzeilig aus der Folie heraus. ``autoFit="resize"`` lässt Storyline die
    Schrift zusätzlich verkleinern, wenn es trotz Umbruch nicht passt — so
    bleibt im Zweifel alles lesbar statt abgeschnitten.
    """
    head_end = frag.index('>') + 1
    head, rest = frag[:head_end], frag[head_end:]
    if 'autoFit="' in head:
        head = re.sub(r'autoFit="[^"]*"', 'autoFit="resize"', head, count=1)
    # Auch die eingebetteten Zustände: eine Antwort liegt fünffach in der Form
    # (Normal, Ausgewählt, Rückblick …). Bliebe dort wrap="none", liefe der
    # Text in der Auswertungsansicht wieder aus der Folie.
    return (head + rest).replace('wrap="none"', 'wrap="true"')


def _set_font_pt(frag: str, pt: float) -> str:
    """Schriftgröße einer Form setzen (``<resize fontSz>``)."""
    return re.sub(r'(<resize\b[^>]*?)fontSz="[\d.]+"', rf'\g<1>fontSz="{pt:g}"',
                  frag, count=1)


def available() -> bool:
    """Ist die Vorlagendatei vorhanden und vollständig?"""
    try:
        with zipfile.ZipFile(ASSET) as z:
            names = set(z.namelist())
            return all(t[0] in names for t in TEMPLATES.values())
    except Exception:
        return False


def supported(qtype: str) -> bool:
    """Kann dieser Fragetyp als Fragefolie gebaut werden?"""
    return qtype in TEMPLATES


class BankTemplate:
    """Die Vorlagendatei im Speicher, plus was beim Klonen unangetastet bleibt."""

    def __init__(self, path: str = ASSET) -> None:
        with zipfile.ZipFile(path) as z:
            self.parts = {i.filename: z.read(i.filename) for i in z.infolist()}
        # GUIDs, die AUSSERHALB der Fragefolien stehen (Layout, Master, Theme,
        # story.xml). Die dürfen beim Klonen NICHT neu vergeben werden, sonst
        # reisst der Verweis nach draussen ab und die Folie hat kein Layout.
        outside: set[str] = set()
        for name, data in self.parts.items():
            if name.startswith(('story/slideLayouts/', 'story/slideMasters/',
                                'story/theme/')) or name == 'story/story.xml':
                outside.update(GUID_RE.findall(data.decode('utf-8', 'replace')))
        self.outside_guids = outside

    def slide(self, qtype: str) -> str:
        return self.parts[TEMPLATES[qtype][0]].decode('utf-8', 'replace')

    def rels(self, qtype: str) -> str:
        part = TEMPLATES[qtype][0].replace('slides/', 'slides/_rels/') + '.rels'
        return self.parts[part].decode('utf-8', 'replace')

    def media(self, qtype: str) -> dict[str, bytes]:
        """Medien, die die Vorlagenfolie über ihre rels braucht."""
        out: dict[str, bytes] = {}
        for target in re.findall(r'Target="([^"]+)"', self.rels(qtype)):
            part = target.lstrip('/')
            if part in self.parts:
                out[part] = self.parts[part]
        return out


def _reguid(xml: str, keep: set[str]) -> str:
    """Alle folien-eigenen GUIDs neu vergeben; Verweise nach aussen bleiben.

    Zwei Folien mit derselben Kennung sind für Storyline ein Widerspruch —
    jede Kopie braucht also eigene GUIDs. Querverweise INNERHALB der Folie
    bleiben heil, weil dieselbe alte GUID überall dieselbe neue bekommt.
    """
    mapping = {g: newg() for g in set(GUID_RE.findall(xml))
               if g != ZERO and g not in keep}
    if not mapping:
        return xml
    return re.compile('|'.join(re.escape(g) for g in mapping)).sub(
        lambda m: mapping[m.group(0)], xml)


def _fmt_doc(text: str) -> str:
    """fmtText-Dokument in der Form, wie Storyline es in ``<text>`` ablegt.

    Das Dokument steht EINFACH escaped im Attribut-losen ``<text>``-Element:
    spitze Klammern als ``&lt;``/``&gt;``, die Anführungszeichen der
    Attribute aber unangetastet. Genau so schreibt es Storyline selbst.
    """
    inner = ('<Document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xmlns:xsd="http://www.w3.org/2001/XMLSchema">  <Content>    <Block>'
             '      <Style FlowDirection="LeftToRight" />      '
             f'<Span Text="{html.escape(text, quote=True)}" />    </Block>  </Content>'
             '</Document>')
    return html.escape(inner, quote=False)


#: Schriftart des Frage-Platzhalters im Storyline-Thema.
TITLE_FONT = 'Open Sans'


def _set_text(frag: str, text: str, pt: float | None = None) -> str:
    """Text einer Form setzen — in ``<plain>`` UND im fmtText (jeweils erstes).

    Mit ``pt`` wird die Größe AUSGESCHRIEBEN. Nötig, weil der Frage-Rahmen ein
    Titel-Platzhalter ist: der Wert in ``<resize fontSz>`` ist nur Storylines
    Merkposten, angewendet wird die Themenschrift (32 pt). Ohne
    ausgeschriebene Größe stand die Frage riesig und einzeilig über den Rand.
    """
    frag = re.sub(r'<plain>[^<]*</plain>', f'<plain>{html.escape(text)}</plain>',
                  frag, count=1)
    if pt:
        doc = fmt_document([[(text, dict(fam=TITLE_FONT, size=f'{pt:g}', color='#000000',
                                         bold=False, ital=False, under=False))]], 'left')
    else:
        doc = _fmt_doc(text)
    frag = re.sub(r'<text>.*?</text>', f'<text>{doc}</text>', frag, count=1, flags=re.S)
    return re.sub(r'<fmtText>.*?</fmtText>', f'<fmtText>{doc}</fmtText>',
                  frag, count=1, flags=re.S)


def _old_text(frag: str) -> str:
    """Der Text, den diese Antwortzeile aus der Vorlage mitbringt."""
    m = re.search(r'<plain>([^<]*)</plain>', frag)
    return html.unescape(m.group(1)) if m else ''


def _retext_row(frag: str, text: str) -> str:
    """Antworttext einer Zeile ersetzen — an ALLEN Stellen.

    Storyline legt den Text einer Antwort fünffach ab: in der Hauptform und in
    den Rückmelde-Zuständen. Wurde nur der erste ersetzt, zeigte die Folie die
    neue Antwort und die Auswertung die alte.
    """
    old = _old_text(frag)
    if not old or old == text:
        return frag
    # Der Text steht in ZWEI Schreibweisen: fünfmal als <plain> und einmal im
    # formatierten Dokument. Storyline zeigt und wertet das FORMATIERTE aus —
    # wurde nur <plain> ersetzt, stand in der Frage weiter „erstens".
    frag = frag.replace(f'<plain>{html.escape(old)}</plain>',
                        f'<plain>{html.escape(text)}</plain>')
    return frag.replace(f'Text="{html.escape(old, quote=True)}"',
                        f'Text="{html.escape(text, quote=True)}"')


def _set_correct(frag: str, correct: bool) -> str:
    """``<scoreData correct="…">`` einer Antwortzeile setzen."""
    return re.sub(r'(<scoreData\b[^>]*?)correct="(?:true|false)"',
                  rf'\g<1>correct="{str(correct).lower()}"', frag, count=1)


def _rows(xml: str, tag: str) -> list[tuple[int, str]]:
    """Antwortzeilen -> [(Startindex im Folien-XML, Element-XML)].

    Nur DIREKTE Kinder von ``<shapeLst>`` zählen. Eine schlichte Suche nach
    ``<radio`` fände auch ``<prstGeom><radio vertexSet="false" /></prstGeom>``
    tief in jeder Form — bei acht Antworten waren das 96 Treffer statt 8.
    """
    si = xml.find('<shapeLst')
    if si < 0:
        return []
    shapes = extract_element(xml, si, 'shapeLst')
    if shapes is None:
        return []
    base = si + shapes.index('>') + 1
    inner = shapes[shapes.index('>') + 1:]
    out: list[tuple[int, str]] = []
    pos = 0
    while pos < len(inner):
        m = re.compile(r'<([A-Za-z][\w]*)').search(inner, pos)
        if not m:
            break
        frag = extract_element(inner, m.start(), m.group(1))
        if frag is None:
            break
        if m.group(1) == tag:
            out.append((base + m.start(), frag))
        pos = m.start() + len(frag)
    return out


class BankSlide:
    """Eine gebaute Fragefolie mit allem, was ins Paket gehört."""

    __slots__ = ('xml', 'rels', 'guid', 'name', 'media')

    def __init__(self, xml: str, rels: str, guid: str, name: str,
                 media: dict[str, bytes]) -> None:
        self.xml, self.rels, self.guid, self.name, self.media = xml, rels, guid, name, media


def build_slide(tpl: BankTemplate, question: dict, title_pt: float = DEFAULT_TITLE_PT,
                choice_pt: float = DEFAULT_CHOICE_PT) -> BankSlide | None:
    """Eine Frage -> Storyline-Fragefolie. ``None``, wenn der Typ nicht geht.

    ``title_pt``/``choice_pt`` sind die Schriftgrößen von Frage und Antworten.
    Der Fragerahmen wächst passend zur Textlänge mit.
    """
    qtype = question.get('type')
    if not supported(qtype):
        return None
    options = [(t, bool(c)) for t, c in question.get('options') or []]
    if not options:
        return None

    _part, intr_tag, choice_tag = TEMPLATES[qtype]
    xml = _reguid(tpl.slide(qtype), tpl.outside_guids)

    # --- Antwortzeilen auf die gebrauchte Anzahl bringen ------------------
    rows = _rows(xml, choice_tag)
    if not rows:
        return None
    if qtype in FIXED_CHOICES:
        options = options[:len(rows)]
    want = len(options)

    while len(rows) < want:
        # Kopie der letzten Zeile: eigene GUIDs, sonst wäre sie dieselbe Form.
        start, frag = rows[-1]
        copy = _reguid(frag, tpl.outside_guids)
        xml = xml[:start + len(frag)] + copy + xml[start + len(frag):]
        rows = _rows(xml, choice_tag)
    while len(rows) > want:
        start, frag = rows[-1]
        xml = xml[:start] + xml[start + len(frag):]
        rows = _rows(xml, choice_tag)

    # --- Texte, Lösung und laufende Nummern setzen ------------------------
    # VON HINTEN nach vorn: jede Ersetzung ändert die Länge des Dokuments und
    # damit alle Positionen dahinter. Vorwärts gelesen zeigten die gemerkten
    # Startpunkte nach der ersten Zeile ins Leere und zerschossen das XML.
    for n in range(len(options) - 1, -1, -1):
        start, frag = rows[n]
        text, correct = options[n]
        new = frag
        if qtype not in FIXED_CHOICES:
            new = _retext_row(new, text)
        new = _set_correct(new, correct)
        new = _set_font_pt(new, choice_pt)
        new = _wrap_inside(new, choice_tag)
        # ``id`` ist bei Reihenfolgefragen die LÖSUNG (Sollposition), sonst nur
        # eine laufende Nummer. In beiden Fällen muss sie eindeutig sein.
        new = re.sub(rf'(<{choice_tag}\b[^>]*?)\sid="-?\d+"', rf'\g<1> id="{n + 1}"',
                     new, count=1)
        xml = xml[:start] + new + xml[start + len(frag):]

    guids: list[str] = []
    for _start, frag in _rows(xml, choice_tag):
        g = re.search(r'\sg="([0-9a-fA-F-]{36})"', frag)
        if g:
            guids.append(g.group(1))

    # --- childLst der Interaktion auf die tatsächlichen Zeilen setzen -----
    i = xml.find('<' + intr_tag)
    if i >= 0:
        intr = extract_element(xml, i, intr_tag)
        if intr:
            new_intr = re.sub(r'<childLst>.*?</childLst>',
                              '<childLst>' + ''.join(f'<g>{g}</g>' for g in guids)
                              + '</childLst>', intr, count=1, flags=re.S)
            xml = xml[:i] + new_intr + xml[i + len(intr):]

    # --- Fragetext --------------------------------------------------------
    title = (question.get('text') or question.get('name') or 'Frage').strip()
    old_title = TITLES[qtype]
    bottom = _title_bottom(title, title_pt)
    ti = xml.find(f'<plain>{html.escape(old_title)}</plain>')
    if ti >= 0:
        box_start = xml.rfind('<textBox', 0, ti)
        if box_start >= 0:
            box = extract_element(xml, box_start, 'textBox')
            if box:
                # Länge des ORIGINALS merken — nach dem Ändern ist sie eine
                # andere, und mit ihr zu schneiden zerreisst das Dokument.
                span = len(box)
                box = _set_text(box, title, title_pt)
                box = _set_font_pt(box, title_pt)
                box = _set_loc(box, _TITLE_TOP, bottom)
                box = _wrap_inside(box, 'textBox')
                xml = xml[:box_start] + box + xml[box_start + span:]

    # Die Antworten rücken nach, damit sie nicht unter der Frage liegen.
    ii = xml.find('<' + intr_tag)
    if ii >= 0:
        intr = extract_element(xml, ii, intr_tag)
        if intr:
            xml = xml[:ii] + _set_loc(intr, bottom + _INTR_GAP, _INTR_BOTTOM) + xml[ii + len(intr):]

    # --- Folienname + eigene Kennung --------------------------------------
    name = (question.get('name') or title)[:80]
    xml = re.sub(r'(<sld\b[^>]*?)\sname="[^"]*"',
                 r'\g<1> name="' + html.escape(name, quote=True) + '"', xml, count=1)
    g = re.search(r'<sld\b[^>]*?\sg="([0-9a-fA-F-]{36})"', xml)
    return BankSlide(xml, tpl.rels(qtype), g.group(1) if g else newg(),
                     name, tpl.media(qtype))


def build_bank(questions: list[dict], title_pt: float = DEFAULT_TITLE_PT,
               choice_pt: float = DEFAULT_CHOICE_PT) -> tuple[list[BankSlide], dict[str, int]]:
    """Alle Fragen -> Fragefolien. Gibt auch zurück, was NICHT gebaut wurde.

    Nicht baubare Fragen sind kein Verlust: sie stehen weiterhin in der
    Importdatei. Sie werden aber gezählt und gemeldet, damit niemand raten
    muss, warum die Bank kürzer ist als das Depot.
    """
    tpl = BankTemplate()
    built: list[BankSlide] = []
    skipped: dict[str, int] = {}
    for q in questions:
        slide = build_slide(tpl, q, title_pt, choice_pt)
        if slide is None:
            skipped[q.get('type') or '?'] = skipped.get(q.get('type') or '?', 0) + 1
            continue
        built.append(slide)
    return built, skipped


def bank_scene_xml(slides: list[BankSlide], name: str = 'Fragen aus imc') -> str:
    """``<scene>``-Eintrag für den ``bankLst`` von ``story.xml``."""
    ids = ''.join(f'<sldId>{relid_from_guid(s.guid)}</sldId>' for s in slides)
    return (f'<scene g="{newg()}" verG="{newg()}" name="" '
            f'desc="{html.escape(name, quote=True)}" '
            f'primaryId="{ZERO}" sceneType="scene" collapse="false" drawG="{ZERO}">'
            f'<sldIdLst>{ids}</sldIdLst><localizedName />'
            f'<bankProps g="{newg()}" verG="{newg()}" rand="false" include="-1" />'
            '</scene>')
