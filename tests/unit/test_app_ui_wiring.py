#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Oberfläche und Skript müssen zueinander passen.

Anlass: bei einem Umbau der Ansicht fiel der ganze Block „Datei wählen" aus
``app.js``. Die Knöpfe blieben im HTML sichtbar, hatten aber keinen Zuhörer
mehr — die App ließ sich nicht mehr benutzen, ohne dass irgendetwas gemeldet
wurde. Beide Richtungen werden deshalb geprüft.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / 'converter_app' / 'web'
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
JS = (WEB / 'app.js').read_text(encoding='utf-8')

#: ids, die nur Beschriftungen tragen (``<label for=...>``) und kein Verhalten
#: brauchen — sie dürfen im Skript fehlen.
_PASSIVE = {'optLang', 'optGeometry'}


def _button_ids(html: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'<button\b[^>]*\bid="([^"]+)"', html)}


def _element_ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def _js_ids(js: str) -> set[str]:
    return set(re.findall(r"\$\('([^']+)'\)", js))


def test_every_button_has_a_listener() -> None:
    """Kein Knopf ohne Verdrahtung — sonst klickt man ins Leere."""
    missing = sorted(b for b in _button_ids(HTML) if f"$('{b}')" not in JS)
    assert not missing, f'Knöpfe ohne Zuhörer in app.js: {missing}'


def test_script_only_addresses_existing_elements() -> None:
    """Umgekehrt: kein ``$('…')`` auf ein Element, das es nicht (mehr) gibt."""
    unknown = sorted(_js_ids(JS) - _element_ids(HTML))
    assert not unknown, f'app.js spricht unbekannte ids an: {unknown}'


def test_interactive_controls_are_read_somewhere() -> None:
    """Jede Option im Kopf muss auch im Export ankommen."""
    opts = {i for i in _element_ids(HTML) if i.startswith('opt')} - _PASSIVE
    unused = sorted(o for o in opts if f"$('{o}')" not in JS)
    assert not unused, f'Optionen ohne Wirkung: {unused}'


# --- Einstellungsfenster ---------------------------------------------------
# Die Schalter stehen seit dieser Fassung in einem eigenen Fenster. Dabei darf
# keiner verlorengehen und keiner ausserhalb hängenbleiben.
def _dialog(html: str) -> str:
    return html[html.index('id="settings"'):html.index('<!-- Großansicht -->')]


def test_every_option_lives_in_the_settings_dialog() -> None:
    inside = set(re.findall(r'id="(opt\w+)"', _dialog(HTML)))
    everywhere = set(re.findall(r'id="(opt\w+)"', HTML))
    assert inside == everywhere, f'ausserhalb des Fensters: {sorted(everywhere - inside)}'


def test_dialog_can_be_opened_and_closed() -> None:
    for name in ('btnSettings', 'setClose', 'setDone', 'setReset'):
        assert f"$('{name}')" in JS, f'{name} ohne Zuhörer'


def test_defaults_cover_every_option() -> None:
    """Ohne Vorgabe wird ein Schalter beim Zurücksetzen vergessen und
    verschwindet aus dem gemerkten Zustand."""
    block = JS[JS.index('const OPTIONS = {'):JS.index('};', JS.index('const OPTIONS = {'))]
    declared = set(re.findall(r'\b(opt\w+):', block))
    present = set(re.findall(r'id="(opt\w+)"', HTML))
    assert declared == present, f'fehlt in OPTIONS: {sorted(present - declared)}'
