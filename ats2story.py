#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ats2story.py — DEPRECATED Monolith (durch das Paket ``ats2story/`` ersetzt).

Diese Datei enthält KEINE Logik mehr. Der frühere 1414-Zeilen-Monolith wurde in
das gleichnamige Paket ``ats2story/`` zerlegt (Module: ats_reader, media, ocr,
richtext, story_writer, converter, cli). Beim Import gewinnt ohnehin das Paket
(Verzeichnis vor Datei) — diese Datei wird nur noch direkt ausgeführt
(``python3 ats2story.py ...``) und delegiert dann an die Paket-CLI.

Bitte die neue CLI verwenden:
    python3 -m ats2story.cli --ats kurs.ats --out kurs.story
"""
from __future__ import annotations


def main() -> None:
    """Delegiert an die Paket-CLI (ats2story.cli)."""
    import os
    import sys

    # Sicherstellen, dass das Paket-Verzeichnis auffindbar ist.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from ats2story.cli import main as cli_main
    cli_main()


if __name__ == '__main__':
    main()
