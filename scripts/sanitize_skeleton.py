#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt aus einer Storyline-Datei ein NEUTRALES Grundgerüst.

Das eingebaute Gerüst (``ats2story/assets/skeleton.story``) ist das einzige
Kurs-Binärformat, das bewusst **versioniert** wird — alle anderen `.story`/`.ats`
sind per ``.gitignore`` ausgeschlossen. Genau deshalb darf es kein Kundenmaterial
enthalten: Logos, Figuren, Fotos, Audio, PDFs oder Kurstexte würden mit jedem
Klon des Repositorys mitwandern und ließen sich aus der Git-Historie auch später
nicht mehr einfach entfernen.

Der Konverter braucht vom Gerüst nur die **Struktur**: Master, Layouts, Theme,
Player-Einstellungen und die drei Form-Schablonen (pic/textBox/sound). Die
eingebetteten Medien werden von Layouts/Mastern zwar referenziert, ihr *Inhalt*
ist aber belanglos. Dieses Skript ersetzt daher jede Mediendatei durch ein
neutrales Gegenstück **gleichen Formats und gleicher Abmessungen** (die
Dateinamen bleiben, damit alle Referenzen gültig bleiben) und überschreibt
Kurstexte sowie Folien-/Szenennamen.

Aufruf::

    python3 scripts/sanitize_skeleton.py QUELLE.story ZIEL.story
"""
from __future__ import annotations

import io
import re
import struct
import sys
import zipfile

#: Platzhaltertexte, die Storyline SELBST in Master/Layouts schreibt — die sind
#: kein Kundeninhalt und bleiben erhalten (sonst sieht das Gerüst kaputt aus).
_STORYLINE_DEFAULTS = re.compile(
    r'^(\s*(Click to edit|Question Choice|Button|Feedback|Seite %|&#x)|\s*$)', re.I)

#: Ersatztext für alles andere.
_NEUTRAL_TEXT = 'Text'

#: Minimales, gültiges 1-seitiges PDF (leer).
_BLANK_PDF = (
    b'%PDF-1.4\n'
    b'1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n'
    b'trailer<</Root 1 0 R>>\n%%EOF\n')


def _png_size(data: bytes) -> tuple[int, int]:
    """Breite/Höhe aus dem IHDR — funktioniert auch bei PNGs, die PIL ablehnt."""
    try:
        w, h = struct.unpack('>II', data[16:24])
        if 0 < w <= 20000 and 0 < h <= 20000:
            return int(w), int(h)
    except Exception:
        pass
    return (16, 16)


def _blank_image(data: bytes, ext: str) -> bytes:
    """Neutrales Bild gleicher Größe (hellgrau) im selben Format."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            size = im.size
    except Exception:
        size = _png_size(data) if ext == 'png' else (16, 16)
    buf = io.BytesIO()
    if ext in ('jpg', 'jpeg'):
        Image.new('RGB', size, (222, 222, 222)).save(buf, 'JPEG', quality=70)
    else:
        Image.new('RGBA', size, (222, 222, 222, 255)).save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _silent_mp3(ms: int = 300) -> bytes:
    """Kurzes stilles MP3 (ersetzt Kursaudio)."""
    try:
        import lameenc
    except ImportError:                       # pragma: no cover
        return b''
    enc = lameenc.Encoder()
    enc.set_bit_rate(64)
    enc.set_in_sample_rate(44100)
    enc.set_channels(1)
    enc.set_quality(7)
    samples = b'\x00\x00' * int(44100 * ms / 1000)
    return enc.encode(samples) + enc.flush()


def _neutral_media(name: str, data: bytes) -> bytes:
    ext = name.rsplit('.', 1)[-1].lower()
    if ext in ('png', 'jpg', 'jpeg'):
        return _blank_image(data, ext)
    if ext == 'mp3':
        return _silent_mp3()
    if data[:5] == b'%PDF-':
        return _BLANK_PDF
    return b''                                # unbekannt -> leeren


#: Attribute mit Datei-HERKUNFT. Storyline merkt sich hier den absoluten Pfad
#: der Originaldatei — im Ausgangsgerüst z.B.
#: ``C:\Users\<name>\OneDrive - <Firma>\...\Bilder\foto.png``. Das verrät
#: Firma, Windows-Benutzerkonto und interne Ordnerstruktur.
_PATH_ATTRS = ('origFile', 'source', 'file')

#: Attribute mit den ursprünglichen Dateinamen der Medien
#: (z.B. ``<Kursname>.mp3``, ``<Firmenlogo>.png``).
#: NICHT ``useFileName`` — das ist trotz des Namens ein Boolean (``true``);
#: leeren erzeugt einen ungültigen Wert (von der Schema-Prüfung gefunden).
_NAME_ATTRS = ('displayName', 'AssetName')

#: 1x1-PNG (transparent) als Ersatz für die base64-Vorschaubilder in
#: ``docProps/summary.xml`` — dort liegt von JEDER Originalfolie ein Screenshot.
_BLANK_PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42m'
                  'NkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')

#: Player-Optionen, deren ``value`` sichtbarer Text ist (Kurstitel im Player).
_TEXT_OPTION = re.compile(r'(<option name="[\w]*(?:title|text|logo|copyright)[\w]*" value=")[^"]*(")',
                          re.I)


def _scrub_xml(text: str) -> str:
    """Kurstexte, Namen, Titel und Herkunftspfade neutralisieren.

    Wichtig: ``fmtText`` liegt DOPPELT escaped im XML — dort steht
    ``&lt;Span Text="…"&gt;`` statt ``<Span Text="…">``. Ein Muster, das auf
    ``<`` verankert, greift deshalb nur einen Bruchteil der Texte.
    """
    def span(m: re.Match) -> str:
        val = m.group(2)
        if _STORYLINE_DEFAULTS.match(val):
            return m.group(0)
        return f'{m.group(1)}Span Text="{_NEUTRAL_TEXT}"'

    # beide Formen: '<Span Text="…"' und '&lt;Span Text="…"'
    text = re.sub(r'(&lt;|<)Span Text="([^"]*)"', span, text)
    # Klartext-Spiegel des Textinhalts (zwei Varianten im Schema)
    text = re.sub(r'<plain>[^<]*</plain>', f'<plain>{_NEUTRAL_TEXT}</plain>', text)
    text = re.sub(r'<text>[^<]*</text>', f'<text>{_NEUTRAL_TEXT}</text>', text)
    # Folien-/Szenennamen: <sld> in den Folien, <slide>/<scene> in der summary
    text = re.sub(r'(<(?:sld|slide)\b[^>]*?\sname=")[^"]*(")', r'\g<1>Folie\g<2>', text)
    text = re.sub(r'(<scene\b[^>]*?\sname=")[^"]*(")', r'\g<1>Szene\g<2>', text)
    for attr in _PATH_ATTRS:
        text = re.sub(rf'\s{attr}="[^"]*"', f' {attr}=""', text)
    for attr in _NAME_ATTRS:
        text = re.sub(rf'\s{attr}="[^"]*"', f' {attr}=""', text)
    # Vorschaubilder der Originalfolien (base64) durch ein 1x1-PNG ersetzen
    text = re.sub(r'(thumbnail=")[A-Za-z0-9+/=]{40,}(")',
                  lambda m: m.group(1) + _BLANK_PNG_B64 + m.group(2), text)
    # Kursvorschaubild im Player (<asset>…</asset>, base64-PNG, ~1,7 MB)
    text = re.sub(r'(<asset>)[A-Za-z0-9+/=]{200,}(</asset>)',
                  lambda m: m.group(1) + _BLANK_PNG_B64 + m.group(2), text)
    text = _TEXT_OPTION.sub(r'\g<1>\g<2>', text)

    # Absolute Pfade in BELIEBIGEN Attributen (auch in escaped eingebetteten
    # Blobs wie dem Publish-State: p:directory="C:\Users\<konto>\<firma>\…").
    text = re.sub(r'="(?:[A-Za-z]:\\\\?|/Users/|/home/)[^"]*"', '=""', text)
    # LMS-Kennungen (Kurs-/Lektionstitel) im eingebetteten Publish-State
    text = re.sub(r'(&lt;(id|title|url)&gt;).*?(&lt;/\2&gt;)', r'\g<1>\g<3>', text)

    # Projekt-Eigenschaften in story.xml: <prop id="18">Autor</prop>,
    # <prop id="23">Kurstitel</prop>. Geleert wird nur MENSCHENLESBARER
    # Freitext (enthält ein Leerzeichen oder Nicht-ASCII) — Token wie
    # "1.0.0.0" und alle Props mit XML-Kindern bleiben unangetastet, damit
    # nichts Strukturelles verlorengeht.
    def prop(m: re.Match) -> str:
        val = m.group(2)
        human = ' ' in val.strip() or any(ord(c) > 127 for c in val)
        return f'{m.group(1)}{m.group(3)}' if human else m.group(0)

    text = re.sub(r'(<prop id="\d+">)([^<]{3,})(</prop>)', prop, text)

    # OPC-Kerneigenschaften: Ersteller/Bearbeiter (Benutzerkonten!) und Titel
    text = re.sub(r'(<dc:creator>).*?(</dc:creator>)', r'\g<1>\g<2>', text)
    text = re.sub(r'(<lastModifiedBy>).*?(</lastModifiedBy>)', r'\g<1>\g<2>', text)
    text = re.sub(r'(<dc:title>).*?(</dc:title>)', r'\g<1>Grundgeruest\g<2>', text)
    return text


def sanitize(src: str, dst: str) -> dict:
    """Neutrales Gerüst schreiben. -> Statistik-dict."""
    stats = dict(media=0, media_bytes_before=0, media_bytes_after=0, xml=0)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith('story/media/'):
                stats['media'] += 1
                stats['media_bytes_before'] += len(data)
                data = _neutral_media(info.filename, data)
                stats['media_bytes_after'] += len(data)
            elif info.filename.endswith(('.xml', '.rels', '.psmdcp')):
                text = data.decode('utf-8', 'strict')
                new = _scrub_xml(text)
                if new != text:
                    stats['xml'] += 1
                data = new.encode('utf-8')
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)
    return stats


def audit(path: str, needles: list[str]) -> list[tuple[str, str]]:
    """Sucht Begriffe im GESAMTEN Archiv (auch in Binärteilen).

    Die Endkontrolle: fällt hier etwas an, ist die Bereinigung unvollständig —
    besser laut scheitern als ein Gerüst mit Kundenresten auszuliefern.
    """
    found: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            data = z.read(name)
            for nd in needles:
                for enc in ('utf-8', 'utf-16-le'):
                    if nd.encode(enc) in data:
                        found.append((nd, name))
                        break
    return found


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    src, dst = sys.argv[1], sys.argv[2]
    needles = sys.argv[3:]
    st = sanitize(src, dst)
    print(f"Medien ersetzt : {st['media']} "
          f"({st['media_bytes_before']/1e6:.1f} MB -> {st['media_bytes_after']/1e6:.1f} MB)")
    print(f"XML bereinigt  : {st['xml']} Parts")
    if needles:
        rest = audit(dst, needles)
        if rest:
            print(f"\n!! {len(rest)} Restfund(e):")
            for nd, part in rest[:20]:
                print(f"   {nd!r} in {part}")
            raise SystemExit(1)
        print(f"Endkontrolle   : keiner der {len(needles)} Begriffe mehr gefunden")


if __name__ == '__main__':
    main()
