#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ats2voice.py  —  Sprach-Korpus-Export  imc Content Studio (.ats) -> Voice-Cloning-Trainingsdaten

Zieht die KOMPLETTE Sprecher-Narration aus einem oder mehreren .ats-Kursen und legt
einen sauberen Trainings-Korpus an — als Input fuer Voice-Cloning (lokal: Fish Speech /
XTTS-v2 / CosyVoice; oder ElevenLabs Professional). Reuse der bewaehrten Extraktion aus
ats2story.py (walk_course, slide_content, mp3_info).

Zwei Stufen:
  1) EXTRAKTION  (immer, keine Abhaengigkeit): jede Audiospur je Folie, md5-dedupliziert,
     sprechend benannt (NNN__Szene__Folie.ext), + manifest.csv (Dauer, Quelle, Bildschirmtext).
  2) NORMALISIERUNG (optional, nur falls ffmpeg installiert): mono, Resample, Stille trimmen,
     Lautheit angleichen (loudnorm) -> clean/*.wav. Ohne ffmpeg wird der Schritt sauber
     uebersprungen (Hinweis: `brew install ffmpeg`).

Aufruf:
    python3 ats2voice.py                          # alle *.ats im Ordner -> ./voice_corpus
    python3 ats2voice.py kurs.ats --out korpus
    python3 ats2voice.py *.ats --normalize        # zusaetzlich clean/*.wav (braucht ffmpeg)
    python3 ats2voice.py kurs.ats --normalize --sr 22050 --min-ms 800

Hinweis Rechte: Stimme einer/eines Verstorbenen -> Einwilligung der Erben/Rechteinhaber
klaeren; kommerzielle Cloning-Dienste verlangen diese Bestaetigung ausdruecklich.
"""
import argparse, csv, hashlib, html, io, os, re, shutil, subprocess, sys, wave, zipfile

# bewaehrte Bausteine aus dem bestehenden Konverter wiederverwenden
from ats2story import walk_course, slide_content, mp3_info


# ----------------------------------------------------------------------------- helpers
def slug(s, maxlen=48):
    s = html.unescape(s or '')
    s = re.sub(r'[\s/\\]+', '_', s.strip())
    s = re.sub(r'[^0-9A-Za-z_À-ſ-]', '', s)   # Umlaute/Akzente erlaubt
    s = re.sub(r'_+', '_', s).strip('_')
    return (s or 'x')[:maxlen]


def audio_ext(b):
    """Dateiendung aus den Magic-Bytes; .ats-Narration ist i.d.R. MP3."""
    if b[:3] == b'ID3' or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
        return 'mp3'
    if b[:4] == b'RIFF' and b[8:12] == b'WAVE':
        return 'wav'
    if b[:4] == b'OggS':
        return 'ogg'
    if b[:4] == b'fLaC':
        return 'flac'
    if b[4:8] == b'ftyp':
        return 'm4a'
    return 'mp3'


def duration_ms(b, ext):
    """Dauer in ms; MP3 frame-genau (aus ats2story), WAV via wave, sonst 0 (unbekannt)."""
    try:
        if ext == 'mp3':
            return mp3_info(b)[0]
        if ext == 'wav':
            w = wave.open(io.BytesIO(b))
            return int(w.getnframes() / w.getframerate() * 1000)
    except Exception:
        pass
    return 0


def rich_to_text(rich):
    """imc richText (HTML) -> einzeiliger Klartext (Bildschirmtext der Folie, NICHT garantiert
    das Narrations-Skript — nur als grobe Hilfe im Manifest)."""
    t = re.sub(r'(?i)<\s*br\s*/?>', ' ', rich or '')
    t = re.sub(r'(?i)</\s*p\s*>', ' ', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    return re.sub(r'\s+', ' ', t).strip()


def have_ffmpeg():
    return shutil.which('ffmpeg') is not None


def ffmpeg_clean(src, dst, sr, trim_db):
    """mono + Resample + Stille an beiden Enden trimmen + Lautheit angleichen -> WAV."""
    trim = (f'silenceremove=start_periods=1:start_silence=0.1:start_threshold={trim_db}dB,'
            f'areverse,'
            f'silenceremove=start_periods=1:start_silence=0.1:start_threshold={trim_db}dB,'
            f'areverse')
    af = f'{trim},loudnorm=I=-23:LRA=7:tp=-2'
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', src,
           '-ac', '1', '-ar', str(sr), '-af', af, dst]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def fmt_dur(ms):
    s = ms // 1000
    return f'{s // 60}m{s % 60:02d}s'


# ----------------------------------------------------------------------------- export
def export(ats_paths, out_dir, do_norm, sr, trim_db, min_ms):
    raw_dir = os.path.join(out_dir, 'raw')
    os.makedirs(raw_dir, exist_ok=True)
    clean_dir = os.path.join(out_dir, 'clean')
    if do_norm:
        os.makedirs(clean_dir, exist_ok=True)

    seen = {}                 # md5 -> rel. raw-Pfad (Dedup ueber alle Kurse hinweg)
    rows = []                 # Manifest-Zeilen
    idx = 0
    total_ms = 0
    skipped_short = 0

    for ats_path in ats_paths:
        if not os.path.isfile(ats_path):
            print(f'  ! nicht gefunden: {ats_path}', file=sys.stderr)
            continue
        course = os.path.splitext(os.path.basename(ats_path))[0]
        print(f'[ats] {course}')
        try:
            atsz = zipfile.ZipFile(ats_path)
            scenes = walk_course(atsz)
        except Exception as e:
            print(f'  ! konnte Kurs nicht lesen: {e}', file=sys.stderr)
            continue

        for scene in scenes:
            for sl in scene['slides']:
                if sl.get('exam') or not sl.get('ata'):
                    continue
                try:
                    items, audio = slide_content(sl['ata'])
                except Exception:
                    continue
                if not audio or not audio.get('bytes'):
                    continue
                b = audio['bytes']
                md5 = hashlib.md5(b).hexdigest()
                if md5 in seen:
                    continue                      # identische Narration nur einmal
                ext = audio_ext(b)
                dur = duration_ms(b, ext)
                if dur and dur < min_ms:
                    skipped_short += 1
                    continue
                idx += 1
                fname = f'{idx:04d}__{slug(scene["name"],24)}__{slug(sl.get("name","Folie"),32)}.{ext}'
                with open(os.path.join(raw_dir, fname), 'wb') as f:
                    f.write(b)
                seen[md5] = fname
                total_ms += dur

                onscreen = ' '.join(rich_to_text(it[2]['rich'])
                                    for it in items if it[1] == 'text' and it[2].get('rich'))
                rows.append(dict(file=f'raw/{fname}', course=course, scene=scene['name'],
                                 slide=sl.get('name', 'Folie'),
                                 audio_name=audio.get('name', ''),
                                 duration_ms=dur, ext=ext, md5=md5,
                                 onscreen_text=onscreen[:500]))

    # Manifest schreiben
    man = os.path.join(out_dir, 'manifest.csv')
    with open(man, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'course', 'scene', 'slide', 'audio_name',
                                          'duration_ms', 'ext', 'md5', 'onscreen_text'])
        w.writeheader()
        w.writerows(rows)

    # optionale Normalisierung
    n_clean = 0
    if do_norm and rows:
        if not have_ffmpeg():
            print('\n  ! --normalize gewuenscht, aber ffmpeg fehlt -> Schritt uebersprungen.')
            print('    Installiere mit:  brew install ffmpeg   und ruf das Script erneut auf.')
        else:
            print(f'\n[clean] normalisiere {len(rows)} Dateien (mono, {sr} Hz, trim, loudnorm) ...')
            for r in rows:
                src = os.path.join(out_dir, r['file'])
                dst = os.path.join(clean_dir, os.path.splitext(os.path.basename(r['file']))[0] + '.wav')
                if ffmpeg_clean(src, dst, sr, trim_db):
                    n_clean += 1

    # Zusammenfassung
    print('\n' + '=' * 60)
    print(f'  Clips (uniq) : {len(rows)}')
    print(f'  Gesamtdauer  : {fmt_dur(total_ms)}  ({total_ms/60000:.1f} min)')
    if skipped_short:
        print(f'  uebersprungen: {skipped_short} (kuerzer als {min_ms} ms)')
    if do_norm:
        print(f'  normalisiert : {n_clean} -> {clean_dir}/')
    print(f'  Rohdaten     : {raw_dir}/')
    print(f'  Manifest     : {man}')
    print('=' * 60)
    if total_ms < 30 * 60000:
        print('  Hinweis: <30 min. Fuer "Professional"/Fine-Tuning gilt: mehr = besser.')
    else:
        print('  Reichlich Material fuer Professional-Cloning / Fine-Tuning.')


def main():
    ap = argparse.ArgumentParser(description='Sprach-Korpus aus .ats fuer Voice-Cloning extrahieren.')
    ap.add_argument('ats', nargs='*', help='.ats-Dateien (Default: alle *.ats im aktuellen Ordner)')
    ap.add_argument('--out', default='voice_corpus', help='Zielordner (Default: voice_corpus)')
    ap.add_argument('--normalize', action='store_true', help='zusaetzlich clean/*.wav (braucht ffmpeg)')
    ap.add_argument('--sr', type=int, default=24000, help='Sample-Rate der clean-WAVs (Default 24000)')
    ap.add_argument('--trim-db', type=int, default=-50, help='Stille-Schwelle in dB (Default -50)')
    ap.add_argument('--min-ms', type=int, default=500, help='Clips kuerzer als X ms ignorieren (Default 500)')
    a = ap.parse_args()

    paths = a.ats or sorted(f for f in os.listdir('.') if f.lower().endswith('.ats'))
    if not paths:
        print('Keine .ats-Dateien gefunden.', file=sys.stderr)
        sys.exit(1)
    export(paths, a.out, a.normalize, a.sr, a.trim_db, a.min_ms)


if __name__ == '__main__':
    main()
