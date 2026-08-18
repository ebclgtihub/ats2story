# ats2voice — Sprach-Korpus aus .ats für Voice-Cloning

Zieht die komplette Sprecher-Narration aus den `.ats`-Kursen und legt einen sauberen
Trainings-Korpus an. Damit lässt sich die Stimme des (verstorbenen) Sprechers für neue
Folien reproduzieren — **kostenlos & lokal** oder über einen Cloud-Dienst.

> **Rechte:** Stimme einer/eines Verstorbenen → Einwilligung der Erben/Rechteinhaber
> klären. Cloud-Cloning-Dienste verlangen diese Bestätigung ausdrücklich.

## 1) Korpus erzeugen

```bash
python3 ats2voice.py                      # alle *.ats im Ordner -> ./voice_corpus
python3 ats2voice.py kurs.ats --out korpus
python3 ats2voice.py kurs.ats --normalize # zusätzlich clean/*.wav (braucht ffmpeg)
```

Ergebnis:
- `voice_corpus/raw/` — eine Datei je Folie, md5-dedupliziert, benannt `NNN__Szene__Folie.ext`
- `voice_corpus/manifest.csv` — Quelle, Szene, Folie, Dauer, Format, md5, Bildschirmtext
- `voice_corpus/clean/` — *(nur mit `--normalize`)* mono / resampled / Stille getrimmt / loudnorm

**Status EASY-BUSINESS-Kurs (DE):** 299 Clips, **~167 min** sauberes WAV (16-bit, mono, 44.1 kHz).
Mehr als genug für Professional-Cloning / Fine-Tuning. Hinweis: im DE-Kurs liegt der
Folientext als Bild vor → `onscreen_text` meist leer (Transkripte ggf. per Whisper, s.u.).

Optionen: `--sr` (clean-Samplerate, Default 24000), `--trim-db` (Stille-Schwelle, Default -50),
`--min-ms` (Mini-Clips ignorieren, Default 500).

## 2) Stimme klonen

### Weg A — kostenlos & lokal (empfohlen)
1. **Zero-Shot zuerst** (kein Training): ein sauberer Referenz-Clip aus `raw/` genügt.
   Modelle: **Fish Speech V1.5**, **XTTS-v2 (Coqui)**, **CosyVoice2** — alle Deutsch, laufen
   auf dem Mac (CPU/MPS). Text rein → Audio raus.
2. **Optional Fine-Tuning** für maximale Ähnlichkeit: auf dem ganzen `raw/`-Korpus.
   Braucht eine GPU → **gratis über Google Colab**; das fertige Modell läuft danach lokal.
   Transkripte erzeugt das Training-Tooling i.d.R. automatisch per Whisper.

### Weg B — Cloud, kostenpflichtig
ElevenLabs **Professional Voice Cloning** (MCP-Server verfügbar: `elevenlabs/elevenlabs-mcp`).
Beste Qualität ohne Setup, aber Bezahlplan (Creator+) und Rechte-Bestätigung nötig.

## 3) Zurück in den Kurs
Das generierte Audio (pro Folie eine Datei) lässt sich wieder in die `.story`-Pipeline
(`ats2story.py`) einhängen, sodass neue/ersetzte Folien die geklonte Stimme bekommen.
```
