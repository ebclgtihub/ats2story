# SPEC — ats2story (imc Content Studio `.ats` → Articulate Storyline `.story`)

Technische Referenz zur Architektur, zum Datenfluss und zu den Optionen des
Konverters. Für die Kurzanleitung siehe `README.md` / `README_ats2story.md`.

---

## 1. Überblick

`ats2story` liest einen imc-Content-Studio-Kurs (`.ats`, ein ZIP aus verschachtelten
`.ata`-ZIPs) und erzeugt ein Articulate-Storyline-Projekt (`.story`, ein OPC-/ZIP-Paket
aus XML-Parts). Übernommen werden **Bilder, Text und Ton** sowie die **Kapitelstruktur**.

Der Code liegt als Python-Paket `ats2story/` vor (früher ein Monolith `ats2story.py`;
diese Datei an der Wurzel ist heute nur noch ein dünner Kompatibilitäts-Shim, siehe §6).

### Einstiegspunkte

| Zweck | Aufruf |
|---|---|
| **Desktop-App (GUI)** | `python3 converter_app/app.py` |
| **Skript / CI / Batch** | `python3 -m ats2story.cli --ats kurs.ats --out kurs.story` |
| **Bibliothek** | `import ats2story; ats2story.convert_ats(ats, out, …)` |
| Kompat-Shim (deprecated) | `python3 ats2story.py …` → delegiert an `ats2story.cli` |

> **Keine externe Vorlage nötig.** Das Storyline-Grundgerüst ist als Paket-Asset
> eingebaut (`ats2story/assets/skeleton.story`). `--tpl` / `tpl=` ist **optional**
> und überschreibt nur das eingebaute Gerüst. Siehe §5.

---

## 2. Paket-Architektur (`ats2story/`)

Viele kleine, kohäsive Module. Öffentliche API wird über `ats2story/__init__.py`
re-exportiert; die Orchestrierung lebt in `converter.py`.

```
ats2story/
├── __init__.py          Re-Export der öffentlichen API + OCR-State-Proxy (§6)
├── converter.py         Orchestrierung: convert_ats() — der Ablauf aus §4
├── cli.py               argparse-CLI (python -m ats2story.cli)
├── types.py             frozen Domain-Typen (SlideSource, SceneSource,
│                          MediaEntry, ConvertStats)
├── geometry.py          imc-Canvas → Storyline-Canvas (1280×720): `Geometry`
│                          (Rects UND Schriftgrößen, canvas-abhängig) sowie die
│                          Modul-Funktionen fit_rect/fill_rect/native_rect
├── guid.py              GUID-/ID-Helfer (Storyline-Konventionen, base62-Relids)
├── security.py          zentrale Härtung (Zip-/XML-/Pfad-Guards), von allen genutzt
│
├── ats_reader/          .ats/.ata LESEN
│   ├── walker.py          walk_course(): Kapitelbaum → Szenen/Folien-Struktur
│   │                        + course_background(): Hintergrundbild/-farbe des Kurses
│   ├── canvas.py          detect_canvas(): imc-Bühnengröße des Kurses erkennen
│   ├── slide_parser.py    eine .ata → Bilder/Texte/Audio (inkl. disabled-Filter,
│   │                        Rotation, Deckkraft, Füllung/Rahmen, Zeilenhöhe)
│   ├── thumbnail.py       Thumbnail-PNG aus einer .ata (für die Vorschau)
│   └── _ns.py             XML-Namespace-Konstante + ET-Import
│
├── media/               MEDIEN
│   ├── pool.py            MediaPool: md5-deduplizierter Pool (Bilder + Audio)
│   ├── image.py           Bild-Re-Encode (PNG non-interlaced / JPG baseline)
│   │                        + Decompression-Bomb-Guard
│   └── audio.py           MP3-Analyse (Dauer/Bitrate/Kanäle), WAV→MP3
│
├── ocr/                 BILD-TEXT → EDITIERBARER TEXT (optional)
│   ├── engine.py          Tesseract: Bild → Roh-Textblöcke (gecacht), Farbe je
│   │                        Textbereich (auch hell auf dunkel)
│   ├── blocks.py          Roh-Blöcke → Storyline-Textblöcke (mit Geometrie-Transform)
│   ├── imagemask.py       Grafikerhalt: Nicht-Text-Anteil messen, Textstellen
│   │                        im Bild ausstempeln statt das Bild zu verwerfen
│   └── config.py          veränderlicher OCR-State (Binary/tessdata/Sprache), §6
│
├── richtext/            TEXT-FORMAT
│   ├── parser.py          imc richText (HTML-Fragment) → (text, style)-Runs
│   └── formatter.py       Runs → Storyline fmtText (Document/Block/Span)
│
├── story_writer/        .story SCHREIBEN
│   ├── template.py        Template: lädt Gerüst, extrahiert Stencils + Preserve-Set
│   ├── shapes.py          Shape-Fragmente (pic/textBox/sound/rels/slide) aus Stencils
│   ├── builder.py         Builder: baut je Folie das slide-XML zusammen
│   ├── patch.py           patcht story.xml (sceneLst/toc/mediaLst/quiz), baut summary/rels
│   ├── backgrounds.py     Vorlagen-Hintergrundbilder → Weiß (Option --clean-bg)
│   └── opc_writer.py       schreibt das fertige OPC-ZIP (write_story_package)
│
└── assets/
    └── skeleton.story    EINGEBAUTES Storyline-Grundgerüst (§5)
```

Domäne (`types.py`, alle `frozen=True`):

- **`SlideSource`** — eine Folie: `ata` (Bytes der `.ata`-ZIP) **oder** `exam=True`
  (Test-/Prüfungs-Platzhalter).
- **`SceneSource`** — eine Szene (= Kapitel/Leaf-Folder) mit ihren Folien.
- **`MediaEntry`** — ein Pool-Eintrag (Bild/Audio) mit `guid/fname/ext/md5/…`.
- **`ConvertStats`** — Ergebnis-Statistik. `convert_ats` gibt bewusst ein `dict`
  (`dataclasses.asdict`) zurück, damit die App-/CLI-Integration stabil bleibt.

---

## 3. Datenfluss

```
.ats (ZIP)
  │  ats_reader.walk_course()
  ▼
Szenen  →  Folien            (Kapitelbaum: 1 Leaf-Folder = 1 Szene; Animationen = Folien)
  │  _filter_scenes()        (chapters / no_exams / single_scene)
  ▼
je Folie:  ats_reader.slide_parser  →  Bilder + richText + Audio
  │
  ├─ media.image   → Re-Encode + MediaPool (md5-dedup)
  ├─ media.audio   → MP3 (Dauer) + MediaPool
  ├─ richtext      → parser → formatter → fmtText
  └─ ocr (opt.)    → engine → blocks → editierbare Textboxen statt Text-Bild
  │
  │  geometry.fit_rect / fill_rect   (imc 1024×748 → Storyline 1280×720)
  │  story_writer.builder.build_slide()  →  slide-XML (+ rels), XML-validiert
  ▼
story_writer.patch  →  story.xml (sceneLst/toc/mediaLst), summary, [Content_Types], .rels
  │  + add_media_pool() / strip_quiz() / clean_backgrounds()
  ▼
story_writer.opc_writer.write_story_package()  →  .story (OPC-ZIP)
```

Ablauf in `convert_ats()` (`converter.py`):

1. **Vorlage laden** — `Template(tpl)`; prüft, dass pic/textBox/sound-Stencils
   im `slide.xml` des Gerüsts vorhanden sind (sonst `ValueError`).
2. optional **Hintergrund säubern** (`clean_bg`).
3. **Kurs lesen** — `walk_course()`, dann `_filter_scenes()`.
4. **Folien bauen** — `_build_slides()`: pro Folie `Builder.build_slide()`,
   jedes erzeugte slide-XML wird sofort mit `ET.fromstring` validiert; kaputte
   Folien werden übersprungen und geloggt.
5. **Rahmen-XML bauen** — `_build_xml()`: `story.xml`, `.rels`, `[Content_Types]`,
   `summary` — jeweils validiert.
6. **Paket schreiben** — `write_story_package()`; Rückgabe `bad` = Ergebnis von
   `zipfile.testzip()` (`None` = ok).
7. **Statistik** — `ConvertStats` → `dict`. Optionaler `progress(frac, msg)`-Callback
   für GUIs (die CLI druckt stattdessen die Meldungen).

---

## 4. Das eingebaute Skelett (`DEF_TPL` / `_default_skeleton()`)

Storyline verweigert Projekte ohne die vollständige „Versions-Ceremony"
(slideMasters / slideLayouts / theme / playerProps …). Früher musste dafür eine
externe, bekannt-gute `.story` als Vorlage mitgegeben werden. **Das ist nicht
mehr nötig:** ein minimales, gestripptes Grundgerüst liegt als Paket-Asset bei.

- **Asset:** `ats2story/assets/skeleton.story` (Master/Layouts/Theme/Player +
  pic/textBox/sound-Stencils in `slide.xml`).
- **`_default_skeleton()`** (`converter.py`) liefert dessen Pfad — funktioniert im
  Dev-Lauf **und** im PyInstaller-Bundle (Fallback über `sys._MEIPASS`).
- **`DEF_TPL`** = Ergebnis von `_default_skeleton()`; Default für `convert_ats(tpl=…)`
  und für `--tpl` in der CLI.
- Die App (`converter_app/app.py`) nimmt `ats2story.DEF_TPL` über
  `find_default_template()` und meldet einen Fehler, falls das Asset fehlt
  („Installation beschädigt?").

`--tpl PFAD` bleibt als **Override** erhalten (z. B. um ein anderes Gerüst zu
testen), ist aber im Normalfall überflüssig.

---

## 5. Optionen

Gemeinsame Parameter von `convert_ats(...)`, der CLI (`ats2story.cli`) und der App
(`converter_app/app.py`). CLI-Flag → App-Checkbox → `convert_ats`-Argument:

| CLI-Flag | App | `convert_ats`-Arg | Wirkung |
|---|---|---|---|
| `--ocr-text` | „Text editierbar machen" | `ocr_text=bool` | Text-Bilder per OCR (Tesseract) in echte, bearbeitbare Textboxen umwandeln. **CLI-Default aus; App-Default an.** |
| — (Env/`OCR_LANG_PREF`) | „OCR-Sprache" | via `ocr.config` | Whitelist der App: `deu` / `pol` / `eng`. |
| `--no-audio` | „Audio einbetten" (invert.) | `no_audio=bool` | Sprecher-MP3s weglassen. |
| `--clean-bg` | „Hintergrund säubern" | `clean_bg=bool` | Vorlagen-Hintergrund (Europakarte etc.) durch Weiß ersetzen. **CLI-Default aus; App-Default an.** |
| `--no-course-bg` | „Kurs-Hintergrund übernehmen" (invert.) | `course_bg=bool` | Hintergrundbild des imc-Kurses (`document.xml` → `backgroundImage`) als unterste, in Storyline löschbare Ebene je Folie. **Default an.** |
| `--geometry fit\|fill\|native` | „Foliengröße" | `geometry=...` | `fit` = einpassen, kein Verlust (Default). `fill` = randlos, schneidet oben/unten ~11,5 % ab. `native` = Story-Size auf den erkannten imc-Canvas, Koordinaten 1:1 (§ Geometrie). |
| `--single-scene` | „Eine Szene" | `single_scene=bool` | Alle Folien in **eine** Szene → sicherstes Öffnen in Storyline. |
| `--scene-name NAME` | — | `scene_name=str` | Szenenname bei `--single-scene` (Default „Kurs"). |
| `--no-exams` | „Prüfungen weglassen" | `no_exams=bool` | Test-Platzhalterfolien überspringen. Die zugehörigen **Quizfragen bleiben erhalten** — sie sind eigene Inhaltsfolien (s. Quizfragen). |
| `--chapters "a,b"` | — | `chapters=str` | nur Kapitel mit passenden Substrings. |
| `--max-slides N` | — | `max_slides=int` | Nur die ersten N Folien (Testen). |
| `--tpl PFAD` | (intern: eingebaut) | `tpl=str` | **Optional** — überschreibt das eingebaute Skelett (§4). |
| `--keep-medialst` | — | `keep_medialst=bool` | DEBUG: `mediaLst` nicht ersetzen. |
| `--keep-quiz` | — | `keep_quiz=bool` | DEBUG: `quizMgr` nicht anfassen. |

### Geometrie (`geometry.py`) und Canvas-Erkennung (`ats_reader/canvas.py`)

Die imc-Bühnengröße hängt am **Geräteprofil des Kurses** und ist NICHT konstant:
belegt sind **1024×748** (DE-Kurs) und **950×630** (PL-Kurs). Storyline rendert
auf **1280×720**.

`detect_canvas(scenes)` bestimmt sie pro Kurs:

1. Größe von `meta/thumbnail.png` in den `.ata` (1:1-Rendering der Folie,
   Mehrheitsentscheid über bis zu 12 Folien) — in beiden Beispielkursen für
   jede Folie exakt canvas-groß.
2. Fallback: maximale Ausdehnung aller `rect`-Angaben, gerundet auf das
   kleinste passende bekannte Profil.
3. Sonst `DEFAULT_CANVAS` = 1024×748.

`Geometry(mode, ats_w, ats_h)` kapselt daraus **beides**:

- **`fit`** (Default) — der gesamte imc-Canvas bleibt sichtbar (Balken möglich),
  **kein Inhaltsverlust**. Faktor `min(1280/w, 720/h)`.
- **`fill`** — füllt die Bühne randlos, Faktor `max(...)`; Überstände werden
  abgeschnitten. Beispiel 1024×748: `(0.0, -107.5, 1280.0, 827.5)`, also je
  ~107,5 px (~11,5 %) oben und unten.
- **`native`** — Identität; die Story-Size wird auf den **erkannten** Canvas
  gestellt (`set_story_size`), imc-Koordinaten bleiben 1:1.

**Schriftgrößen** (`Geometry.font_pt`): imc-`fontSize` und die `font-size`-Angaben
im richText sind **Pixel auf dem imc-Canvas**, Storyline speichert **Punkt**.
Umrechnung: `pt = px × Canvas-Faktor × 0,75`. Ohne sie landete „18" als 18 pt
(= 24 px) in der .story — Text war rund ein Drittel zu groß und lief aus den
Textboxen.

---

## 5a. Treue-Regeln (was wie übernommen wird)

Ziel ist, dass **alles in Storyline bearbeitbar** ankommt — Text als echte
Textboxen, Grafik als eigenes Bild-Shape, Hintergrund als löschbare Ebene.

| imc-Quelle | Behandlung |
|---|---|
| `text` + `richText` | echte Storyline-Textbox; `<p>` **und** `<br>` = Blockgrenze (s.u.) |
| `fontFamily/fontSize/textColor/fontBold/Italic/Underline` | Grundstil der Box; `fontSize` px → pt |
| `<span style="...">` | überschreibt je Run: `color`, `font-size` (px → pt), `font-family`, `font-weight`, `font-style`, `text-decoration` — **auch die neutralen Werte** (`normal`/`none`) setzen den Grundstil zurück, weil imc sie ausdrücklich schreibt |
| `disabled="true"` | Element wird übersprungen (im imc-Player unsichtbar) — gilt für Bild, Text und Audio |
| `lineHeight` | Zeilenabstand als `LineSpacingRule="Exactly"` in Punkt (s.u.) |
| `rotation` | `rot`-Attribut am Shape in Grad (`-1` = keine Rotation) |
| `fill` / `stroke` am Textelement | `<solidFill>` / `<solidLine>` im `<bG>` + Rahmenbreite im `<lineStyle>` |
| `opacity` am Bild | in den Alphakanal des Bildes gerechnet (s.u.) |
| `image` | Bild-Shape an transformiertem Rect |
| `audiotrack` | Sound-Shape |
| `document@duration` | Standzeit der Folie; Folienlänge = max(5 s, Audiodauer, imc-Dauer) |
| Kurs-`backgroundImage` | ganzflächiges Bild-Shape als **unterste** Ebene je Folie (`course_bg`) |
| Ordner mit Folien **neben** Unterordnern | eigene Szene (früher fielen diese Folien weg) |

Noch **nicht** übernommen: `contentMargin` (das Skelett-Stencil hat kein
`<margins>`-Element, und die Position im Schema ist unbelegt — in beiden
Beispielkursen ist der Wert ohnehin durchgehend 0), `occurrence`-Einblendzeiten
und `effect`-Animationen. Zu `occurrence`: von ~1500 Elementen der beiden Kurse
tragen **zwei** einen anderen Wert als das voreingestellte `start="0" end="-1"` —
der Aufwand stünde in keinem Verhältnis.

### Quizfragen (`.ati`) — 69 Folien, die vorher fehlten

Fragen liegen **nicht** im Kapitelbaum, sondern als `.ati`-Dateien in einem
`<vault>`-Fragenpool. Eine `<exam>` verweist über
`<questionpoolcollection><folderpool referenceId="…">` auf den Pool-Ordner.
Weil `walk_course` nur den Kapitelbaum lief, blieb von jedem Test nur der
Platzhalter „[TEST] …" — **alle 72 Frageseiten des DE-Kurses fehlten**.

Eine `.ati` benutzt ansonsten **dasselbe Schema wie eine `.ata`**
(image/text/rect) und wird deshalb vom selben Parser gelesen; hinzu kommen die
Interaktionselemente:

| Typ | Anzahl (DE) | Übernahme |
|---|---|---|
| `singlechoiceinteraction` | 33 | Optionen aus `<singlechoice>`, richtige über `correctIndex` |
| `multiplechoiceinteraction` | 33 | Optionen aus `<multiplechoice>`, richtige über `checked="true"` |
| `draganddropinteraction` | 5 | Beschriftungen der `<dragsource>` + Hinweis auf der Folie |
| `textgapinteraction` | 1 | Lösungen aus `<textgap>` |

Die Optionen landen als **editierbare Textbox**: richtige Antwort fett und mit
`●`, falsche mit `○`. Ein echtes Storyline-Quiz lässt sich aus dem Gerüst nicht
erzeugen (es enthält keine Quiz-Schablonen, und `strip_quiz` entfernt den
`quizMgr`) — so ist die Frage aber vollständig da und in Storyline nachbaubar,
ohne im Quellkurs zu suchen.

### Fragen als Articulate-Importdatei (`quiz_export.py`)

Besser als die Textbox-Darstellung: Storyline kann Fragen aus einer Excel- oder
Textdatei importieren und daraus **echte, auswertbare Quizfolien** bauen. Der
Konverter legt deshalb neben der `.story` zwei Dateien ab —
`…_Fragen.xlsx` und `…_Fragen.txt` (Option `quiz_export`, Default an).
Import in Storyline: *Datei > Import > Fragen aus Datei*.

Format laut Articulate: Feldreihenfolge **Fragetyp · Punkte · Fragetext ·
Antwortoptionen**, richtige Antworten mit vorangestelltem `*`, `//` leitet
Kommentare ein, höchstens 10 Optionen je Frage.

| imc | Articulate | Anmerkung |
|---|---|---|
| `singlechoiceinteraction` | `MC` | bei genau zwei Optionen „Richtig/Falsch" → `TF` |
| `multiplechoiceinteraction` | `MR` | richtige über `checked="true"` |
| `textgapinteraction` | `FIB` | Lösungen aus `<textgap>` |
| `draganddropinteraction` | `SD` | Reihenfolgefrage, s.u. |

**Die Lösung von Drag&Drop steckt in den Ablagezielen:** jedes `<droptarget>`
verweist per `<dragsourcereference>` auf die richtige Quelle, und die
Reihenfolge ergibt sich aus der Position der Ziele (oben nach unten). Die
`<dragsource>`-Folge ist dagegen nur die gemischte Anzeigereihenfolge und wäre
als Lösung falsch. Am Beispielkurs geprüft: Gesprächsvorbereitung →
Gesprächseinstieg → Bedarfserhebung → Präsentation → Abschluss.

Der Fragetext ist der längste Textblock der Folie (die Kopfzeile trägt den Namen
der Übung und wird ausgeschlossen).

Das XLSX wird **ohne Fremdbibliothek** geschrieben — ein XLSX ist ein ZIP aus
wenigen XML-Teilen, und dieses Projekt schreibt mit dem `.story`-Paket ohnehin
ein deutlich komplexeres OPC-Format. Gegengeprüft mit `openpyxl` als
unabhängiger Implementierung.

Ausbeute: „Kurs A" 45 Fragen (MC 13, MR 28, TF 3, SD 1), DE-Kurs
72 Fragen (MC 20, MR 33, TF 13, SD 5, FIB 1), „Kurs B (Prüfungskurs)"
207 Fragen (MR 111, TF 70, MC 22, SD 3, FIB 1).

**Fragen werden standardmäßig KEINE Folien** (`quiz_slides=False`). Als Folie
wäre eine Frage nur eine statische Abbildung; über die Importdatei entsteht in
Storyline eine echte, auswertbare Quizfolie. In fragenlastigen Kursen ist der
Unterschied drastisch: „Kurs B (Prüfungskurs)" besteht aus **1 Inhaltsfolie
und 207 Fragen** — als Folien ergäbe das ein Deck, in dem der Inhalt untergeht.
`--quiz-slides` bzw. die Checkbox legt sie zusätzlich an.

> **Reihenfolge beachten:** Die Fragen werden eingesammelt, *bevor* sie aus der
> Folienliste fallen. Wird zu früh gefiltert, bleibt die Importdatei leer —
> genau dieser Fehler war schon einmal drin und ist jetzt durch einen Test
> abgedeckt.

### Depot-Ansicht in der App

Die Vorschau zeigt Fragen nicht als Kacheln, sondern als **Depot** — den
Ordnerbaum, den imc selbst benutzt (Depot > Buch > Test Übung 1 …), mit Anzahl
je Ordner und dem Hinweis, dass daraus die Excel-Datei entsteht. Die Kursleiste
fasst alle Fragen zu einem Segment „Depot" zusammen; bei 19 Szenen, von denen 18
Fragenordner sind, zerfiele sie sonst in unlesbare Stummel.

Schriftgröße: eigene Angabe der Interaktion, sonst 25 px — im imc-Rendering
einer Frageseite nachgemessen (Zeilenhöhe 30 px bei 57 px Zeilenabstand). 61 der
72 Interaktionen setzen `fontSize="-1"` (Player-Vorgabe), 11 setzen 18–27 px.

**Mehrfachnutzung:** Kapiteltests, Sammeltests und der Prüfungskurs greifen auf
denselben Pool zu — 191 Referenzen auf 69 eindeutige Fragen (bis zu 3× dieselbe).
Ausgegeben wird jede Frage **genau einmal**, beim ersten Test, der sie zieht;
die Platzhalterfolie nennt die Gesamtzahl und wie viele davon bereits weiter
oben stehen.

**Fragen ohne Prüfungsbezug:** Der Pool enthält regelmäßig mehr Fragen, als die
Prüfungen ziehen. Im Kurs „Kurs A" liegen **45 Fragen** im Vault,
die einzige Prüfung referenziert **5**. Der imc-Publisher exportiert trotzdem
alle — sein Protokoll listet sie, gruppiert nach den Vault-Ordnern. Deshalb
erzeugt `_vault_scenes()` für jeden Vault-Ordner mit noch nicht ausgegebenen
Fragen eine eigene Szene (`„Classic / Phasen"`). Ohne diesen Schritt gingen dort
40 von 45 Fragen verloren, im DE-Kurs 3 von 72.

### Der SCORM-Export als Referenz

imc kann den Kurs als SCORM-Paket veröffentlichen. Darin liegt **imc's eigenes
Renderingmodell**: `content/manifest.json.txt` listet die Folien in Reihenfolge,
und jedes `content/<guid>/<guid>.json.txt` beschreibt eine Folie vollständig.
Das ist die belastbarste Referenz, die ohne Storyline erreichbar ist — jede
Annahme dieses Konverters lässt sich daran prüfen:

| Was der Export sagt | Bestätigt |
|---|---|
| `"width":"1024px","height":"748px"` in der Folien-CSS | der erkannte Canvas |
| `left/top/width/height` je Element in px | unsere Koordinaten 1:1 |
| `font-size: 25px` (deckungsgleich mit `.ata`-`fontSize`) | Schriftgrößen sind PIXEL → px→pt-Umrechnung |
| `line-height: 1.25` — unitloser CSS-Faktor, auf **allen** 102 Textelementen | Zeilenabstand = Schriftgröße × 1,25, also `LineSpacingRule="Exactly"` |
| `duration` je Folie in ms | unsere Zehntelsekunden-Umrechnung — **alle 10 Werte identisch** |
| `background-image: url(content/assets/_globalbackground.png)` | Kurs-Hintergrund, **bytegleich** mit dem, was wir aus `document.xml` lesen |
| `font-family` (Source Sans Pro Light 90×, Arimo 7×, Open Sans 5×) | unsere Schriften-Zählung |
| 405 der 407 `shape`-Elemente in `groups: ["feedback-*"]` | Quiz-Chrome zur Laufzeit, **kein fehlender Inhalt** |
| alle `keyFrames` auf `time: 0` | keine Animationen zu erhalten (`occurrence`) |

`scripts/verify_against_export.py` automatisiert den Vergleich: es ordnet die
Folien über den Titel zu (unsere Reihenfolge folgt dem Kapitelbaum, der Export
listet den Fragenpool am Stück) und prüft je Textelement Vorhandensein,
Position und Schriftgröße.

```bash
python3 scripts/verify_against_export.py kurs.story export.zip
```

Stand für „Kurs A" (`geometry native`): **102 Textelemente, kein
fehlender Text, keine Positionsabweichung über 4 px, keine falsche
Schriftgröße.**

### Das Publisher-Protokoll als Gegenprobe

imc schreibt beim Export ein `publisherlog_*.log` mit einer Zeile
`Exporting "<Name>"` je Element, dazu `Creating audio track` und die benötigten
Web-Fonts. Das ist eine **unabhängige Inhaltsliste** des Kurses und eignet sich
hervorragend als Soll-Vergleich: genau daran ist der Vault-Verlust aufgefallen
(66 Log-Einträge gegen 16 gefundene Folien). Die verbleibende Differenz sind
Ordner- und Kursnamen, die bei uns zu Szenennamen werden.

### Schriften-Hinweis

imc liefert Web-Fonts mit dem Kurs aus (das Protokoll nennt sie unter
`Copying web font`), Storyline kann das nicht. Fehlt eine Schrift auf dem
Storyline-Rechner, ersetzt Storyline sie durch eine beliebige andere — mit
anderen Zeichenbreiten verschiebt sich der Umbruch. `ConvertStats.fonts` zählt
daher die verwendeten Schriften und die Abschlussmeldung nennt sie. Beispiel
„Kurs A": Source Sans Pro Light (90×), Arimo (7×), Open Sans (5×) —
deckungsgleich mit dem, was das imc-Protokoll meldet. Nur metrisch gleichwertige
Paare werden ersetzt (s. Schriftersatz); alles andere bleibt stehen und muss
installiert sein.

### Foliendauer

`document@duration` in der `.ata` zählt **Zehntelsekunden** — empirisch bestimmt
über die 11 Folien des PL-Kurses, deren Sprecheraufnahmen sich zum Attribut wie
100,7 : 1 verhalten. Die Folienlänge ist `max(5 s, Audiodauer, imc-Dauer)`; das
Maximum stellt sicher, dass **nie etwas abgeschnitten** wird, sondern nur auf die
von imc gesetzte Standzeit verlängert. Betroffen sind 4 von 11 PL- und 3 von 60
DE-Folien (+0,06 s bis +3,2 s).

`autoFit` bleibt bewusst auf dem Stencil-Wert `resize`, obwohl imc durchgehend
`autoSize="false"` (fester Kasten) meldet: unsere Schrift- und Fontersetzung ist
nicht pixelgenau, ein fixer Kasten würde im Zweifel Text abschneiden.

### Zeilenabstand: `Exactly`, nicht `Multiple`

imc rechnet CSS-artig — der Zeilenabstand ist **Schriftgröße × lineHeight**.
Im imc-Rendering des Beispielkurses nachgemessen: `fontSize="13"` mit
`lineHeight="125"` ergibt **16 px** Zeilenabstand (= 13 × 1,25).

Storylines `Multiple` bezieht sich dagegen auf dessen **eigenen** einfachen
Abstand (`LineSpacing="20"`), der bereits ~1,2 em beträgt — `Multiple/25` würde
die Leerräume also doppelt zählen. Übernommen wird deshalb
`LineSpacingRule="Exactly"` mit dem absoluten Wert in Punkt
(`Schriftgröße_pt × lineHeight/100`), die Form, die auch in den
Storyline-Referenzdateien vorkommt (dort u.a. `Exactly/18.75` = 15 × 1,25).
Der Wert wird **je Block aus dessen größter Schrift** bestimmt.

Nachmessung am erzeugten Ergebnis: Zeilenabstand imc **16 px**, unsere .story
**16 px**.

### Zeilenumbruch: `<br>` wird zur Blockgrenze

Storyline kennt **keinen weichen Zeilenumbruch**. In einer von Storyline selbst
geschriebenen Datei (714 Textfelder) enthält kein einziges `<Span Text="…">` ein
Steuerzeichen, und ein `<Br>`-Tag existiert im fmtText-Schema nicht — jede Zeile
ist ein eigener `<Block>` (Ø 1,6 Blöcke je Textfeld).

`<br>` wird deshalb wie `<p>` als Blockgrenze behandelt. Mit
`SpacingBefore="0"`/`SpacingAfter="0"` rendert das wie ein Zeilenumbruch. Der
Stil-Stack läuft über die Grenze weiter, ein `<br>` innerhalb eines
`<span style="…">` verliert dessen Formatierung also nicht.

> Zwischenzeitlich stand hier U+2028 (Line Separator). Das war geraten: in
> Storyline-Dateien kommt das Zeichen **null** mal vor.

### Schriftersatz (metrisch gleichwertig)

imc-Kurse sind in **Arimo** gesetzt — einem der Google-Croscore-Klone, die
zeichenbreitengleich zu den Microsoft-Kernschriften entworfen wurden. Auf einem
Storyline-Rechner ist Arimo praktisch nie installiert; Storyline ersetzt sie
dann durch eine beliebige Fallback-Schrift mit anderen Breiten, und der Umbruch
verschiebt sich. `richtext.map_font` bildet deshalb auf das metrische
Gegenstück ab (Arimo/Liberation Sans → Arial, Tinos → Times New Roman,
Cousine → Courier New, Carlito → Calibri, Caladea → Cambria). **Unbekannte
Schriftnamen bleiben unverändert** — ersetzt wird nur, was nachweislich
gleiche Zeichenbreiten hat.

### Bild-Deckkraft

Storyline hat am `picFormat` ein `trans`-Attribut, dessen Wert in **allen**
vorliegenden Referenzdateien ausschließlich `0` ist — die Skala ist damit
unbelegt. Statt sie zu raten, rechnet `media.apply_opacity` die imc-Deckkraft in
den Alphakanal des PNG. Das Ergebnis stimmt garantiert, und das Bild bleibt ein
normales, austauschbares Bild-Shape.

> Rotation, Füllung/Rahmen und Deckkraft kommen in **beiden** vorliegenden
> Kursen nicht vor (durchgehend `rotation="0"`, `opacity="100"`,
> `fill/stroke style="0"`). Sie ändern an deren Ausgabe also nichts und sind
> ausschließlich durch Unit-Tests abgesichert (`tests/unit/test_shape_attrs.py`).

### OCR: Grafik bleibt erhalten

Findet OCR Text in einem Bild, wird gemessen, wie viel „Tinte" **außerhalb** der
Textkästen liegt (`imagemask.nontext_ink_ratio`):

- **< 15 %** → praktisch reine Textgrafik: Bild wird wie bisher komplett durch
  Textboxen ersetzt.
- **≥ 15 %** → Diagramm/Screenshot mit Beschriftung: das Bild **bleibt**, nur die
  Textstellen werden mit der lokalen Hintergrundfarbe überstempelt
  (`erase_text_regions`), die Textboxen liegen darüber.

Die Schriftfarbe kommt **je Textkasten** aus dessen Bildausschnitt (häufigste
Luminanz = Hintergrund, die am weitesten entfernten Pixel = Schrift). Damit
funktioniert auch **helle Schrift auf dunklem Grund**; vorher lieferte die
globale Schätzung dafür ein dunkles `#222222` — unsichtbar auf dunklem Bild.

> **Wichtig für Builds:** Die TSV-Ausgabe wird per `-c tessedit_create_tsv=1`
> angefordert, **nicht** über den Config-Namen `tsv`. Der ist eine Datei in
> `tessdata/configs/`, die in gebündelten tessdata-Verzeichnissen fehlt —
> Tesseract lieferte dann Klartext, die TSV-Auswertung fand null Wörter und
> **OCR war im App-Bundle stillschweigend wirkungslos**.

---

## 5b. Wie „öffnet sich die Datei?" ohne Storyline geprüft wird

Zwei Stufen, beide automatisiert:

1. **`validate_story.py`** — prüft alle Storyline-Quer-Referenzen im erzeugten
   Paket (sldId ↔ rels ↔ Parts ↔ Content-Types ↔ toc ↔ mediaLst, dangling rels).
2. **`tests/integration/test_schema_conformance.py`** — vergleicht unsere
   Folien-XML gegen eine Datei, die **Storyline selbst geschrieben hat** (die
   mitgelieferte Vorlage, > 86 000 Elemente). Geprüft wird genau das, woran
   OPC-Formate praktisch scheitern:
   - kein Element, das Storyline nie schreibt,
   - kein Attribut, das es an diesem Element nie schreibt,
   - kein Pflichtattribut fehlt (eines, das Storyline bei diesem Element
     *immer* setzt),
   - kein Aufzählungswert außerhalb der Storyline-Wertemenge.

Stand der Prüfung über OCR-Lauf, `geometry='fill'` und den DE-Kurs mit Audio
(zusammen 27 698 Elemente): **keine strukturelle Abweichung**. Übrig bleiben
nur freie Werte (RGB-Farben, Schriftnamen) und `FontIsUnderline="True"` — dessen
Schreibweise über `FontIsBold="True"`/`FontIsItalic="True"` in derselben Datei
belegt ist.

> Das ersetzt kein Öffnen in Storyline und behauptet es auch nicht. Es schließt
> die Fehlerklasse aus, die zu „invalid or corrupt" führt.

---

## 5c. Datenschutz: das Gerüst muss neutral sein

`ats2story/assets/skeleton.story` ist das **einzige** Kurs-Binärformat, das
bewusst versioniert wird — `.gitignore` schließt sonst alle `.ats`/`.story` aus.
Es stammt aus einer echten Storyline-Datei und enthielt ursprünglich:

| Fundstelle | Inhalt |
|---|---|
| `story/media/` (10 Dateien, 2,7 MB) | Kundenlogo, Figuren, Fotos, **2 MP3s**, ein **PDF** |
| `docProps/summary.xml` (3 MB) | **53 base64-Vorschaubilder** je Originalfolie |
| `story/playerProps.xml` (1,8 MB) | **1,7-MB-Kursvorschaubild** als base64 |
| `story/story.xml`, `theme.xml` | `origFile`/`source`/`p:directory` mit `C:\Users\<konto>\OneDrive - <Firma>\…` |
| `*.psmdcp` | `dc:creator`, `lastModifiedBy` — **Windows-Benutzerkonten** |
| `<prop id="18">`, `<prop id="23">` | Autorenname und Kurstitel |
| fmtText / `<plain>` / `<text>` | Kurstexte, Folien- und Szenennamen |

Der Konverter braucht davon **nichts**: er benutzt nur die Struktur (Master,
Layouts, Theme, Player) und die drei Form-Schablonen. `scripts/sanitize_skeleton.py`
ersetzt daher jede Mediendatei durch ein neutrales Gegenstück gleichen Formats
und gleicher Abmessungen (Dateinamen bleiben, damit die Referenzen gültig
bleiben) und überschreibt Texte, Namen, Pfade und Metadaten. Ergebnis: **7,0 MB
→ 1,0 MB**, Testlauf und Schema-Konformität unverändert.

```bash
python3 scripts/sanitize_skeleton.py ROH.story ats2story/assets/skeleton.story \
  Firmenname Kursname Benutzerkonto      # Begriffe für die Endkontrolle
```

Das Skript **scheitert laut**, wenn einer der genannten Begriffe die Bereinigung
überlebt. `tests/unit/test_skeleton_privacy.py` hält den Zustand dauerhaft fest
(Größe, absolute Pfade, Metadaten, Medienumfang, base64-Blöcke, Kurstexte) —
gegen das unbereinigte Gerüst schlagen alle sechs Prüfungen an.

> **Git-Historie:** Ein Austausch der Datei entfernt die alte Fassung NICHT aus
> der Historie. Soll das Repository je öffentlich werden, muss die Historie
> bereinigt (z.B. `git filter-repo`) oder neu aufgesetzt werden.

Ebenfalls neutralisiert: `DEF_ATS` in `converter.py` (stand auf dem Dateinamen
eines Kundenkurses und erschien damit im ausgelieferten Paket) und die
Fixture-Pfade in `tests/conftest.py` (suchen jetzt per Muster bzw. über
`reference.story`/`ATS_FIXTURE_TPL`).

---

## 6. Kompatibilität & veränderlicher OCR-State

- **`ats2story.py` (Wurzel)** — deprecated. Enthält keine Logik mehr; bei `import`
  gewinnt ohnehin das Paket (Verzeichnis vor Datei). Direkt ausgeführt
  (`python3 ats2story.py …`) delegiert es an `ats2story.cli`.
- **OCR-State-Proxy** (`__init__.py`) — Namen wie `TESSERACT_CMD`, `OCR_TESSDATA`,
  `OCR_LANG_PREF` werden auf `ats2story` **geschrieben** (z. B. von der App). Ein
  simpler Re-Export würde diese Zuweisungen nicht an die Engine durchreichen.
  Deshalb hängt das Modul seine Klasse auf einen Proxy um, der genau diese Namen
  transparent auf `ats2story.ocr.config` umleitet (Lesen **und** Schreiben) — die
  Engine liest `config.*` zur Laufzeit, `ats2story.TESSERACT_CMD = …` wirkt sofort.

---

## 7. Verpacken (Desktop-App)

- **macOS:** `bash packaging/build_macos.sh` (stuft `tessdata` vor, ruft
  `packaging/build.spec` via PyInstaller). Ergebnis: `dist/ATS Converter.app`.
  Gebündelt: App + `web/` + Engine + eingebautes Skelett + Tesseract-Binary + `tessdata`.
- **Windows:** `.github/workflows/build-windows.yml` (PyInstaller, `dist/ATS Converter/`).
  Der Workflow hat gebaut (`dist/ATS-Converter-1.0.0-rc*-windows.zip`); das
  Paket enthält `ATS Converter.exe`, `tesseract.exe`, `tessdata` und das
  eingebaute Gerüst.

### Plattform-Unterschiede (macOS / Windows)

Die Engine (`ats2story/`) ist plattformneutral — kein `sys.platform`, kein
`os.name`, keine absoluten Pfade. Plattformabhängig ist nur die App-Schale:

| Thema | macOS | Windows |
|---|---|---|
| Dateidialog | `webview.FileDialog` | out-of-process über PowerShell/WinForms (WebView2 blockiert sonst den GUI-Thread) |
| Ordner zeigen | `open -R` | `explorer /select,` |
| Tesseract | `tesseract` + dylibs | `tesseract.exe` |
| Ergebnis des Builds | `ATS Converter.app` (signiert/notarisiert) | `dist/ATS Converter/` mit `.exe` |

Zwei Fallstricke, die nur unter Windows auftreten, sind ausdrücklich behandelt:

- **Konsolenfenster.** Die App ist windowed (`console=False`). Ohne
  `CREATE_NO_WINDOW` öffnet Windows für **jeden** Tesseract-Aufruf kurz ein
  schwarzes Fenster — bei einem Kurs mit über tausend Bildern entsprechend oft.
  `ocr.engine._no_window()` setzt das Flag; auf macOS/Linux existiert es nicht
  und der Wert ist 0.
- **Pfadtrenner im OPC-Paket.** ZIP-Einträge werden per String-Verkettung mit
  `/` gebildet, nie mit `os.path.join` — sonst entstünden unter Windows
  Backslashes und Storyline könnte das Paket nicht lesen
  (`test_zip_entry_names_are_posix`).
- Das eingebaute Skelett wird über `datas` mitgebündelt und über `sys._MEIPASS`
  gefunden — im Bundle ist also ebenfalls **keine externe Vorlage** nötig.

---

## 8. Drag & Drop (Startfläche der App)

Die App unterstützt **kein Drag & Drop** — die `.ats`-Datei wird ausschließlich
per **Klick** über den nativen Dateidialog gewählt. Grund: ein HTML5-Drop im
WKWebView liefert keinen echten OS-Dateipfad, und pywebview (6.2.1) stellt kein
Datei-Drop-Event bereit; `convert_ats` braucht aber einen echten Pfad. Die
Startfläche ist daher **ehrlich als Klick-Öffner** gestaltet (solide Umrandung,
Ordner-Symbol, `.opener` in `web/`) und nicht als Drop-Ziel. Detail-Begründung im
Docstring von `converter_app/app.py`.
