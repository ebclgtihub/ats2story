# ats2story — imc Content Studio (.ats) → Articulate Storyline (.story)

Konvertiert komplette imc-Content-Studio-Kurse in Storyline-Projekte mit **Bildern, Text und Ton**.

> **Keine externe Vorlage mehr nötig.** Das Storyline-Grundgerüst ist als Paket-Asset
> eingebaut (`ats2story/assets/skeleton.story`); `--tpl` / `tpl=` ist optional.
> Architektur, Datenfluss und alle Optionen: [`SPEC.md`](SPEC.md).

## Einstiegspunkte

| Zweck | Aufruf |
|---|---|
| **Desktop-App (GUI)** | `python3 converter_app/app.py` |
| **Skript / CI / Batch** | `python3 -m ats2story.cli --ats kurs.ats --out kurs.story` |
| **Bibliothek** | `import ats2story; ats2story.convert_ats(ats, out, …)` |
| Kompat-Shim (deprecated) | `python3 ats2story.py …` → delegiert an `ats2story.cli` |

## Benutzung (CLI)

```bash
# Kompletter Kurs (Kapitel = Szenen)
python3 -m ats2story.cli --ats kurs.ats --out kurs.story

# Sicherste Struktur: alle Folien in EINER Szene
python3 -m ats2story.cli --ats kurs.ats --single-scene --scene-name "Mein Kurs" --out kurs.story

# Nur bestimmte Kapitel / wenige Folien (zum Testen)
python3 -m ats2story.cli --ats kurs.ats --chapters "Einleitung,Werbung" --out test.story
python3 -m ats2story.cli --ats kurs.ats --max-slides 8 --out test.story

# Optionen (Auszug — vollständig in SPEC.md)
--ats PFAD          Quell-.ats
--tpl PFAD          OPTIONAL — überschreibt das eingebaute Skelett
--ocr-text          Text-Bilder per OCR zu editierbaren Textboxen machen
--no-audio          Ton weglassen
--no-exams          Test-/Quiz-Platzhalter weglassen
--single-scene      alle Folien in eine Szene
--clean-bg          Vorlagen-Hintergrund (Europakarte etc.) durch Weiß ersetzen
--geometry fit|fill letterbox (Default) oder randlos (Crop oben/unten ~11,5 %)
```

Die **Desktop-App** (`python3 converter_app/app.py`) bietet dieselben Optionen als
Häkchen plus Folien-Vorschau. Die `.ats` wird per **Klick** über den nativen
Dateidialog gewählt — **kein Drag & Drop** (WKWebView liefert beim Drop keinen
OS-Dateipfad, pywebview 6.2.1 hat kein Datei-Drop-Event; siehe [`SPEC.md` §8](SPEC.md)).

## Was übertragen wird

- **Bilder** — alle PNG/JPG, dedupliziert, non-interlaced re-encodiert, an Originalposition
  (`fit`: Letterbox 1024×748 → 1280×720; `fill`: randlos, Crop oben/unten ~11,5 %).
- **Text** — echte Textfelder (richText → Storyline-fmtText mit Font/Größe/Farbe/Fett/Kursiv).
- **OCR** (optional) — Text-Bilder → editierbare Textboxen (Tesseract, `deu`/`pol`/`eng`).
- **Ton** — MP3-Narration je Folie als Auto-Play-Sound ab Timeline 0.
- **Struktur** — Kapitel → Szenen, Inhaltsverzeichnis, Navigation.
- Quizze/Interaktionen werden als `[TEST]`-Platzhalter angelegt (Storyline-Quizlogik manuell nachbauen).

## Werkzeuge

- `converter_app/app.py` — die Desktop-App (Vorschau + Export).
- `ats2story/` — der Converter (Paket); CLI via `python3 -m ats2story.cli`.
- `validate_story.py kurs.story` — prüft ALLE Storyline-Quer-Referenzen (XML, sldId/rel/part/ctype/toc/assetG/md5, dangling rels). Muss „KEINE FEHLER" melden.
- `render_story.py kurs.story slide.xml,slide2.xml` — rendert Folien aus dem Paket selbst zu PNG (Bild/Text-Kontrolle ohne Storyline).

## Hinweise

- **Vorlage ist eingebaut** (`ats2story/assets/skeleton.story`, liefert slideMasters/slideLayouts/theme).
  `--tpl` bleibt als Override für ein anderes, bekannt gutes Gerüst derselben Storyline-Version.
- Mediendateinamen werden aus der Asset-GUID abgeleitet (Storyline-Anforderung).
- imc-PNGs mit abgeschnittenem IEND werden via `LOAD_TRUNCATED` voll geladen.
