#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durchläuft einen .ats-Kurs und baut die Szenen-/Folien-Struktur auf."""
from __future__ import annotations

import zipfile

from ..security import safe_zip_read
from ._ns import ET, NS


def course_background(ats: zipfile.ZipFile) -> dict:
    """Kurs-Hintergrund aus ``document/document.xml`` -> ``{color, image, name}``.

    imc legt Hintergrundfarbe (Attribut ``backgroundColor``) und ein optionales
    Hintergrundbild (``complexproperty name="backgroundImage"``) auf KURS-Ebene
    ab; Folien ohne eigenes Vollflächenbild zeigen ihn. ``image`` sind die
    Bytes der Ressource (oder ``None``).
    """
    out: dict = dict(color=None, image=None, name='Hintergrund')
    try:
        root = ET.fromstring(safe_zip_read(ats, 'document/document.xml'))
    except Exception:
        return out
    col = (root.get('backgroundColor') or '').strip()
    if col:
        out['color'] = col
    for c in root.findall(NS + 'complexproperty'):
        if c.get('name') != 'backgroundImage':
            continue
        res = c.find(NS + 'resource')
        if res is None:
            continue
        path = res.get('path')
        if not path:
            continue
        try:
            out['image'] = safe_zip_read(ats, path)
            out['name'] = res.get('originalName') or 'Hintergrund'
        except Exception:
            out['image'] = None
    return out


def _question_key(inter) -> str:
    """Identität einer Quizfrage für die Mehrfach-Erkennung.

    ``referenceId``/``id`` sind in echten Kursen immer gesetzt; als Rückfall
    dient der Pfad der ``.ati`` — inhaltlich sogar die genauere Identität, weil
    dieselbe Datei dieselbe Frage ist. Ohne diesen Rückfall würde eine Frage
    ohne beide Attribute stillschweigend verschwinden.
    """
    res = inter.find('.//' + NS + 'resource')
    return (inter.get('referenceId') or inter.get('id')
            or (res.get('path') if res is not None else None)
            or f'obj:{id(inter)}')


def walk_course(ats: zipfile.ZipFile) -> list[dict]:
    """-> Liste Szenen ``[{name, slides:[{name, ata}|{exam:True, name}]}]``.

    Leaf-Subfolder = Szene; Top-Level-Animationen ('Start') -> eigene erste
    Szene. Die Rückgabe bleibt absichtlich ein dict (App liest ``sc['name']``,
    ``s['ata']`` etc.).
    """
    root = ET.fromstring(safe_zip_read(ats, 'document/document.xml'))
    scenes: list[dict] = []

    def ata_bytes_of(anim) -> bytes | None:
        res = anim.find('.//' + NS + 'resource')
        if res is None:
            return None
        p = res.get('path')
        try:
            return safe_zip_read(ats, p)
        except Exception:
            return None

    # Fragen liegen NICHT im Kapitelbaum, sondern in einem <vault> als Pool;
    # eine <exam> verweist über <questionpoolcollection><folderpool referenceId>
    # auf den zugehörigen Ordner. Ohne diese Auflösung fehlten im DE-Kurs alle
    # 72 Quizfolien — es blieb nur der Platzhalter „[TEST] …".
    folders_by_ref = {f.get('referenceId'): f for f in root.iter(NS + 'folder')
                      if f.get('referenceId')}

    # Dieselbe Frage wird von mehreren Tests genutzt (Kapiteltest + Sammeltest
    # + Prüfungskurs, bis zu 3x). Ausgegeben wird sie NUR EINMAL — beim ersten
    # Test, der sie zieht; sonst stünden im DE-Kurs 191 Folien für 69 Fragen.
    emitted_questions: set[str] = set()

    def exam_questions(exam) -> tuple[list[dict], int]:
        """Fragen (.ati) einer Prüfung -> (neue Folien, Gesamtzahl der Fragen)."""
        qpc = exam.find(NS + 'questionpoolcollection')
        if qpc is None:
            return [], 0
        out: list[dict] = []
        refs: list[tuple[str, object]] = []
        seen: set[str] = set()
        for fp in qpc.findall(NS + 'folderpool'):
            folder = folders_by_ref.get(fp.get('referenceId'))
            if folder is None:
                continue
            # iter(): Pool-Ordner können Unterordner haben.
            for inter in folder.iter(NS + 'interaction'):
                ref = _question_key(inter)
                if ref not in seen:
                    seen.add(ref)
                    refs.append((ref, inter))
        for ref, inter in refs:
            if ref in emitted_questions:
                continue
            b = ata_bytes_of(inter)
            if b is None:
                continue
            emitted_questions.add(ref)
            out.append(dict(name=inter.get('name') or 'Frage', ata=b, quiz=True))
        return out, len(refs)

    def collect_slides(folder) -> list[dict]:
        slides: list[dict] = []
        for c in folder:
            tag = c.tag.replace(NS, '')
            if tag == 'animation':
                b = ata_bytes_of(c)
                if b is not None:
                    slides.append(dict(name=c.get('name') or 'Folie', ata=b))
            elif tag == 'interaction':
                # Quizfolien liegen als .ati vor und nutzen dasselbe Schema wie
                # .ata (image/text/rect) plus die Antwortoptionen. Sie wurden
                # bisher komplett übersprungen — im DE-Kurs 72 Folien.
                b = ata_bytes_of(c)
                if b is not None:
                    slides.append(dict(name=c.get('name') or 'Frage', ata=b, quiz=True))
            elif tag in ('exam', 'test'):
                name = c.get('name') or c.get('title') or 'Test'
                questions, total = exam_questions(c)
                slides.append(dict(exam=True, name=name, q_total=total,
                                   q_new=len(questions)))
                slides.extend(questions)
        return slides

    # Top-Level-Animationen (z.B. "Start")
    top_anims = [c for c in root if c.tag == NS + 'animation']
    if top_anims:
        sl = []
        for a in top_anims:
            b = ata_bytes_of(a)
            if b is not None:
                sl.append(dict(name=a.get('name') or 'Start', ata=b))
        if sl:
            scenes.append(dict(name='Start', slides=sl))

    def recurse(folder, inherited_name: str | None = None) -> None:
        # Eigene Folien JEDES Ordners übernehmen — nicht nur die von Blättern.
        # (Früher: nur Blatt-Ordner; Folien, die neben Unterordnern lagen,
        # fielen ersatzlos weg.)
        sl = collect_slides(folder)
        if sl:
            scenes.append(dict(name=folder.get('name') or inherited_name or 'Kapitel',
                               slides=sl))
        for ch in folder:
            if ch.tag == NS + 'folder':
                recurse(ch, ch.get('name'))

    for c in root:
        if c.tag == NS + 'folder':
            recurse(c)

    scenes.extend(_vault_scenes(root, ata_bytes_of, emitted_questions))
    return scenes


def _vault_scenes(root, ata_bytes_of, emitted: set[str]) -> list[dict]:
    """Fragen aus dem ``<vault>``, die KEINE Prüfung referenziert.

    Der Fragenpool enthält regelmäßig mehr Fragen, als die Prüfungen ziehen: im
    Kurs „Kurs A" liegen 45 Fragen im Vault, die einzige Prüfung
    referenziert davon 5. Der imc-Publisher exportiert trotzdem ALLE — sein
    Protokoll listet sie, gruppiert nach den Vault-Ordnern. Ohne diesen Schritt
    gingen dort 40 von 45 Fragen verloren (im DE-Kurs 3 von 72).

    Je Vault-Ordner mit eigenen Fragen entsteht eine Szene; bereits über eine
    Prüfung ausgegebene Fragen werden übersprungen.
    """
    vault = root.find(NS + 'vault')
    if vault is None:
        return []
    out: list[dict] = []

    def visit(folder, path: str) -> None:
        name = folder.get('name') or 'Fragen'
        full = f'{path} / {name}' if path else name
        slides = []
        for inter in folder.findall(NS + 'interaction'):
            key = _question_key(inter)
            if key in emitted:
                continue
            b = ata_bytes_of(inter)
            if b is None:
                continue
            emitted.add(key)
            slides.append(dict(name=inter.get('name') or 'Frage', ata=b, quiz=True))
        if slides:
            out.append(dict(name=full[:80], slides=slides))
        for ch in folder.findall(NS + 'folder'):
            visit(ch, full)

    for folder in vault.findall(NS + 'folder'):
        visit(folder, '')
    return out
