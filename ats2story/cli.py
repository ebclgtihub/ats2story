#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kommandozeilen-Schnittstelle: python3 -m ats2story.cli ..."""
from __future__ import annotations

import argparse

from .converter import DEF_ATS, DEF_TPL, convert_ats


def build_parser() -> argparse.ArgumentParser:
    """argparse-Parser (rückwärtskompatibel zu den alten Flags)."""
    ap = argparse.ArgumentParser(prog='ats2story',
                                 description='Konverter imc Content Studio (.ats) -> Articulate Storyline (.story)')
    # Positional optional (überschreibt --ats), damit beide Aufrufformen gehen:
    #   python3 -m ats2story.cli --ats kurs.ats   UND   ... kurs.ats
    ap.add_argument('ats_pos', nargs='?', default=None, help='Quell-.ats (optional positional)')
    ap.add_argument('--ats', default=DEF_ATS)
    ap.add_argument('--tpl', default=DEF_TPL)
    ap.add_argument('--out', default='kurs.story')
    ap.add_argument('--chapters', default=None, help='Komma-Substrings; nur passende Kapitel')
    ap.add_argument('--max-slides', type=int, default=0)
    ap.add_argument('--no-audio', action='store_true')
    ap.add_argument('--ocr-text', action='store_true',
                    help='Text-Bilder per OCR (deu) zu editierbaren Textboxen rekonstruieren')
    ap.add_argument('--no-exams', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--exams', action='store_true',
                    help='Platzhalterfolien der imc-Prüfungen anlegen '
                         '(Default: weglassen)')
    ap.add_argument('--single-scene', action='store_true',
                    help='Alle Folien in EINE Szene (geringstes Öffnen-Risiko)')
    ap.add_argument('--scene-name', default='Kurs', help='Name der Szene bei --single-scene')
    ap.add_argument('--keep-medialst', action='store_true',
                    help='DEBUG: mediaLst NICHT ersetzen (alle Alt-Einträge + Dateien behalten)')
    ap.add_argument('--keep-quiz', action='store_true', help='DEBUG: quizMgr nicht anfassen')
    ap.add_argument('--clean-bg', action='store_true',
                    help='Vorlagen-Hintergründe (Europakarte etc.) durch Weiß ersetzen')
    ap.add_argument('--geometry', choices=('fit', 'fill', 'native'), default='fit',
                    help="'fit' (letterbox, kein Verlust), 'fill' "
                         "(Vollbild, Crop oben/unten ~11,5%%) oder 'native' "
                         "(Story-Size = imc-Canvas, Koordinaten 1:1)")
    ap.add_argument('--quiz-slides', action='store_true',
                    help='Quizfragen ZUSÄTZLICH als Folien anlegen (Default: nur Importdatei)')
    ap.add_argument('--quiz-export', action='store_true',
                    help='Quizfragen ZUSÄTZLICH als Articulate-Importdatei ablegen '
                         '(.xlsx/.txt neben der .story)')
    ap.add_argument('--no-quiz-export', action='store_true',
                    help=argparse.SUPPRESS)   # alt, wirkungslos (Default ist jetzt AUS)
    ap.add_argument('--quiz-font-pt', type=float, default=None,
                    help='Schriftgröße der Fragen in der Fragenbank (Default 18,5; '
                         'die Antworten wachsen im selben Verhältnis mit)')
    ap.add_argument('--no-quiz-bank', action='store_true',
                    help='Fragen NICHT als Storyline-Fragenbank in die .story legen')
    ap.add_argument('--no-course-bg', action='store_true',
                    help='Kurs-Hintergrundbild aus dem .ats NICHT übernehmen')
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    ats = args.ats_pos or args.ats
    convert_ats(ats, args.out, tpl=args.tpl, chapters=args.chapters,
                max_slides=args.max_slides, no_audio=args.no_audio, ocr_text=args.ocr_text,
                no_exams=not args.exams, single_scene=args.single_scene, scene_name=args.scene_name,
                keep_medialst=args.keep_medialst, keep_quiz=args.keep_quiz, clean_bg=args.clean_bg,
                geometry=args.geometry, course_bg=not args.no_course_bg,
                quiz_export=args.quiz_export, quiz_slides=args.quiz_slides,
                quiz_bank=not args.no_quiz_bank, quiz_font_pt=args.quiz_font_pt)


if __name__ == '__main__':
    main()
