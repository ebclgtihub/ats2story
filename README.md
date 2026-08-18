# ats → story Converter

Konvertiert Kurse aus **imc Content Studio** (`.ats`) nach **Articulate Storyline** (`.story`)
mit **Bildern, Text und Ton**.

> **Keine externe Vorlage mehr nötig.** Das Storyline-Grundgerüst ist eingebaut
> (`ats2story/assets/skeleton.story`); `--tpl` ist optional. Details in [`SPEC.md`](SPEC.md).

## Einstiegspunkte

| Zweck | Aufruf |
|---|---|
| **Desktop-App (GUI)** | `python3 converter_app/app.py` |
| **Skript / CI / Batch** | `python3 -m ats2story.cli --ats kurs.ats --out kurs.story` |
| **Bibliothek** | `import ats2story; ats2story.convert_ats(ats, out, …)` |
| Kompat-Shim (deprecated) | `python3 ats2story.py …` → delegiert an `ats2story.cli` |

Die eigentliche Logik liegt im Paket `ats2story/` (Module: `ats_reader`, `media`,
`ocr`, `richtext`, `story_writer`, `geometry`, `converter`, `cli`). Die Datei
`ats2story.py` an der Wurzel ist nur noch ein dünner Kompatibilitäts-Shim.

## Werkzeuge

| Datei | Zweck |
|---|---|
| `converter_app/app.py` | Desktop-App (Vorschau + Export), macOS/Windows |
| `ats2story/` | Der Converter (Paket) — CLI via `python3 -m ats2story.cli` |
| `validate_story.py` | Prüft ein erzeugtes `.story` auf alle Storyline-Quer-Referenzen (offline) |
| `render_story.py` | Rendert erzeugte Folien aus dem `.story` selbst zu PNG (Inhalts-Beweis ohne Storyline) |
| `diag_build.py` | Baut Diagnose-Dateien D1–D2 zum Eingrenzen von Öffnen-Problemen |

## Nutzung (CLI)

```bash
# Kompletter Kurs
python3 -m ats2story.cli --ats kurs.ats --out kurs.story

# Nur bestimmte Kapitel (Substring-Match)
python3 -m ats2story.cli --ats kurs.ats --chapters "Einleitung,Werbung" --out teil.story

# Klein zum Testen
python3 -m ats2story.cli --ats kurs.ats --max-slides 8 --out test.story

# Häufige Optionen (vollständig in SPEC.md)
#   --ats PFAD        Quell-.ats
#   --tpl PFAD        OPTIONAL — überschreibt das eingebaute Skelett
#   --ocr-text        Text-Bilder per OCR zu editierbaren Textboxen machen
#   --no-audio        Ton weglassen
#   --exams           Test-Platzhalterfolien anlegen (Default: weglassen)
#   --single-scene    alle Folien in EINE Szene (sicherstes Öffnen)
#   --clean-bg        Vorlagen-Hintergrund durch Weiß ersetzen
#   --no-course-bg    Hintergrundbild des imc-Kurses NICHT übernehmen
#   --no-quiz-bank    Fragen NICHT als Storyline-Fragenbank in die .story legen
#   --quiz-export     Fragen ZUSÄTZLICH als Importdatei (.xlsx/.txt) ablegen
#   --quiz-slides     Fragen ZUSÄTZLICH als Folien anlegen (statische Abbildung)
#   --quiz-font-pt N  Schriftgröße der Fragen in der Bank (Default 18,5)
#   --geometry fit|fill|native   einpassen (Default), randlos (Crop oben/unten
#                     ~11,5 %) oder Original-Maße des Kurses 1:1

# Prüfen / ansehen
python3 validate_story.py kurs.story
python3 render_story.py kurs.story slide.xml,slide2.xml
```

Die **Desktop-App** (`python3 converter_app/app.py`) bietet dieselben Optionen als
Häkchen plus Folien-Vorschau. Die Datei wird per Klick über den Dateidialog gewählt
(kein Drag & Drop, siehe [`SPEC.md` §8](SPEC.md)).

## Wie es funktioniert

- **Eingebautes Skelett** (`ats2story/assets/skeleton.story`) liefert die komplette
  Storyline-Versions-Ceremony (slideMasters / slideLayouts / theme / playerProps …).
  Davon werden alle Folien und der Medienpool ersetzt, Layout-/Master-Medien bleiben
  erhalten. `--tpl` überschreibt das Skelett nur bei Bedarf.
- **Kapitelbaum** der `.ats` → Szenen (ein Leaf-Ordner = eine Szene), Animationen → Folien.
- **Bilder**: PNG non-interlaced / JPG baseline re-encodiert, md5-dedupliziert,
  Dateiname aus Asset-GUID abgeleitet (Storyline-Anforderung), Media-Pool + Rel + pic-Shape.
- **Text**: `richText`-HTML → Storyline `fmtText` (Document/Block/Span) mit Font/Größe/Farbe/Stil.
- **Ton**: MP3-Narration je Folie als `<sound>`-Shape, Auto-Play ab Timeline 0.
- **OCR** (optional): Text-Bilder → editierbare Textboxen (Tesseract, `deu`/`pol`/`eng`).

Vollständige Architektur, Datenfluss und alle Optionen: [`SPEC.md`](SPEC.md).

## Verifikationsstand

Offline (ohne Storyline) vollständig geprüft:

- `validate_story.py`: 0 Fehler — alle sldId/Rel/Part/Content-Type/toc/assetG/md5-Referenzen
  konsistent, **keine dangling Rels**.
- Paket-Integrität: unveränderte Parts byte-identisch zum Gerüst, UTF-8-BOM erhalten,
  compress_type je Part erhalten, keine doppelten GUIDs.
- Struktur: erzeugte `story.xml` und Folien **element-/attribut-isomorph** zum (funktionierenden)
  Gerüst; keine Fremd-Tags.
- Inhalt: `render_story.py` zeigt Bilder + Text **deckungsgleich** mit den Original-`.ata`-Thumbnails;
  Audio sind valide MP3 mit korrekten Dauern.

**Offen:** finaler Öffnen-/Wiedergabe-Test in Storyline 3.102 (nur in der Ziel-Anwendung möglich).

## Behobene Fallstricke (Details in der Projekt-Memory)

- Gelöschte, aber von Layouts/Masters referenzierte Medien → „invalid or corrupt" (jetzt erhalten).
- Fehlender UTF-8-BOM in erzeugten `.rels` (jetzt ergänzt).
- `<sld id>` muss `0` sein wie im Gerüst.
- imc-PNGs mit abgeschnittenem IEND → `ImageFile.LOAD_TRUNCATED_IMAGES = True`.
