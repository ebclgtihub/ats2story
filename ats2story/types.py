#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen domain types für den .ats -> .story Konverter.

Diese Typen sind bewusst klein und unveränderlich (``frozen=True``). Die
Konvertierung baut intern damit Strukturen auf; die öffentliche ``convert_ats``
Rückgabe bleibt aber ein ``dict`` (via :func:`dataclasses.asdict`), um die
bestehende App-Integration nicht zu brechen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlideSource:
    """Eine einzelne Folie aus dem .ats-Kurs.

    Entweder eine echte Folie (``ata`` = Bytes der .ata-ZIP) oder ein
    Test/Exam-Platzhalter (``exam=True``)."""

    name: str
    ata: bytes | None = None
    exam: bool = False


@dataclass(frozen=True)
class SceneSource:
    """Eine Szene (= Kapitel/Leaf-Folder) mit ihren Folien."""

    name: str
    slides: tuple[SlideSource, ...] = ()


@dataclass(frozen=True)
class MediaEntry:
    """Ein Eintrag im Medienpool (Bild oder Audio)."""

    guid: str
    fname: str
    ext: str
    md5: str
    is_audio: bool
    dur: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class ConvertStats:
    """Statistik einer Konvertierung. ``asdict`` liefert die Keys, die
    ``converter_app/app.py`` und die CLI lesen."""

    out: str
    slides: int
    scenes: int
    media: int
    size: int
    ocr_replaced: int
    ocr_conf: int
    bad: object  # zipfile.testzip(): None bei Erfolg, sonst Dateiname
    skipped_imgs: int
    skipped_slides: int
    skipped_audio: int
    ocr_errors: int
    skipped_detail: list[str] = field(default_factory=list)
    #: Im Kurs verwendete Schriftarten mit Häufigkeit, häufigste zuerst
    #: (``[(name, anzahl), ...]``). imc liefert Web-Fonts mit dem Kurs aus;
    #: Storyline kann das nicht und ersetzt fehlende Schriften durch eine
    #: beliebige andere — mit anderen Zeichenbreiten verschiebt sich der
    #: Umbruch. Die Liste sagt, was auf dem Storyline-Rechner vorhanden sein
    #: sollte.
    fonts: list = field(default_factory=list)
    #: Pfade der geschriebenen Articulate-Importdateien für die Quizfragen
    #: (``…_Fragen.xlsx`` / ``.txt``); leer, wenn der Kurs keine Fragen hat.
    quiz_files: list = field(default_factory=list)
    #: Wie viele Fragen als Fragenbank in der .story liegen …
    bank_slides: int = 0
    #: … und welche Typen dort nicht gebaut werden konnten ({typ: anzahl}).
    bank_skipped: dict = field(default_factory=dict)
