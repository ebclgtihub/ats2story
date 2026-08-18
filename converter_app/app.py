#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATS → Storyline Converter — Desktop-App (pywebview).

Ablauf:  .ats-Datei wählen  →  Folien-Vorschau  →  als .story exportieren.

Läuft identisch auf macOS und Windows (pywebview nutzt das jeweils native
WebView). Die Konvertierung kommt aus ats2story.convert_ats().

Die Vorschaubilder werden NICHT über die JS-Brücke geschickt (im WebView
unzuverlässig bei vielen Bildern), sondern von einem kleinen lokalen
HTTP-Server ausgeliefert — jede Kachel lädt ihr Bild als normales <img src>.

KEIN Drag&Drop (bewusst): Die Datei wird ausschließlich per Klick über den
nativen Dateidialog (``pick_ats`` -> ``create_file_dialog``) gewählt. Ein
HTML5-Drop im WKWebView liefert KEINEN echten OS-Dateipfad (nur einen Blob
ohne Pfad), und pywebview 6.2.1 stellt kein Datei-Drop-Event bereit (die
``window.events`` kennen nur closed/loaded/shown/resized/moved … — kein
``drop``/``file_drop``). Ein ``convert_ats`` braucht aber einen echten Pfad.
Deshalb ist die Startfläche im UI ehrlich als Klick-Öffner gestaltet (solide
umrandeter Folienrahmen mit Passermarken) und NICHT als Drop-Ziel — siehe
web/index.html / web/style.css (``.opener``). Kommt in einer künftigen pywebview-Version ein
Datei-Drop-Event, kann hier ein ``window.events.<drop>``-Handler ergänzt und
die Fläche wieder als Drop-Ziel ausgewiesen werden.
"""
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import webview

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ats2story  # noqa: E402
from ats2story.ocr import config as _ocr_config  # noqa: E402
from ats2story.quiz_export import question_from_slide  # noqa: E402

import json  # noqa: E402


# --------------------------------------------------------------------------- Pfade
def resource_path(*parts):
    """Pfad zu einer mitgelieferten Ressource — Dev-Lauf UND PyInstaller-Bundle."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


WEB_DIR = resource_path('web')
_ACCESS_LOG = os.path.join(tempfile.gettempdir(), 'ats_app_http.log')
_ERR_LOG = os.path.join(tempfile.gettempdir(), 'ats_app_error.log')

#: Erlaubte OCR-Sprachen, die das Frontend setzen darf (Whitelist).
_ALLOWED_LANGS = {'deu', 'pol', 'eng'}


def _log_err(where):
    """Uncaught-Fehler in eine Log-Datei schreiben — die App ist windowed
    (kein Konsolen-Output), sonst wären Fehler beim Endnutzer unsichtbar.
    Datei: %TEMP%/ats_app_error.log bzw. $TMPDIR/ats_app_error.log."""
    try:
        with open(_ERR_LOG, 'a', encoding='utf-8') as f:
            f.write(f'\n--- {where} ---\n')
            traceback.print_exc(file=f)
    except Exception:
        pass


def configure_bundled_ocr():
    """Im PyInstaller-Bundle: gebündeltes Tesseract-Binary + tessdata verdrahten.
    Im Dev-Lauf passiert nichts (System-Tesseract via PATH wird genutzt)."""
    if not getattr(sys, '_MEIPASS', None):
        return
    exe_name = 'tesseract.exe' if os.name == 'nt' else 'tesseract'
    tcmd = resource_path('tesseract', exe_name)
    tdata = resource_path('tessdata')
    if os.path.isfile(tcmd):
        try:
            os.chmod(tcmd, 0o755)
        except Exception:
            pass
        _ocr_config.TESSERACT_CMD = tcmd
    if os.path.isdir(tdata):
        _ocr_config.OCR_TESSDATA = tdata
    _ocr_config.reset_lang_cache()


#: Erlaubte Schriftgrößen für die Fragenbank (Whitelist gegen Unsinn aus dem
#: Frontend; None = Vorgabe der Vorlage).
_ALLOWED_QUIZ_PT = {14.0, 18.5, 24.0}


def _quiz_font_of(opts) -> float | None:
    """Schriftgröße der Fragen aus den Frontend-Optionen, geprüft."""
    try:
        pt = float(opts.get('quiz_font_pt') or 0)
    except (TypeError, ValueError):
        return None
    return pt if pt in _ALLOWED_QUIZ_PT else None


#: Erlaubte Foliengrößen-Modi aus dem Frontend (Whitelist).
_ALLOWED_GEOMETRY = {'fit', 'fill', 'native'}


def _geometry_of(opts) -> str:
    """Foliengröße aus den Frontend-Optionen — mit Rückfall auf das Alt-Feld.

    Neu ist ein Auswahlfeld ``geometry``; ältere Frontends schickten nur die
    Checkbox ``fill``. Unbekannte Werte fallen auf 'fit' zurück.
    """
    geo = str(opts.get('geometry') or '').strip().lower()
    if geo in _ALLOWED_GEOMETRY:
        return geo
    return 'fill' if opts.get('fill') else 'fit'


def find_default_template():
    """Eingebautes Storyline-Grundgerüst — keine externe Vorlage mehr nötig."""
    return ats2story.DEF_TPL if os.path.isfile(ats2story.DEF_TPL) else None


def _winforms_filter(file_types):
    """pywebview-Filter-Tupel (``'Text (*.ext)'``) -> WinForms-Filterstring
    (``'Text (*.ext)|*.ext|...'``). Muster steht in den Klammern des Textes."""
    parts = []
    for f in file_types:
        a, b = f.find('('), f.rfind(')')
        pattern = f[a + 1:b] if a != -1 and b > a else '*.*'
        parts.append(f + '|' + pattern)
    return '|'.join(parts) if parts else 'Alle Dateien (*.*)|*.*'


def _win_dialog_ctypes(save: bool, file_types, default_name: str = '') -> str | None:
    """Windows-Dateidialog direkt über comdlg32 — ohne fremden Prozess.

    Der frühere Weg über PowerShell war von der Ausführungsrichtlinie und der
    Startzeit der Shell abhängig; blieb er hängen, stand die App ohne
    erkennbaren Grund auf „Reagiert nicht". Der Systemaufruf braucht weder
    Shell noch Rechte. ``hwndOwner=0`` ist Absicht: der Dialog gehört keinem
    Fenster, kann also die Nachrichtenschleife der App nicht blockieren.
    """
    import ctypes
    from ctypes import wintypes

    class OPENFILENAME(ctypes.Structure):
        _fields_ = [('lStructSize', wintypes.DWORD),
                    ('hwndOwner', wintypes.HWND),
                    ('hInstance', wintypes.HINSTANCE),
                    ('lpstrFilter', wintypes.LPCWSTR),
                    ('lpstrCustomFilter', wintypes.LPWSTR),
                    ('nMaxCustFilter', wintypes.DWORD),
                    ('nFilterIndex', wintypes.DWORD),
                    ('lpstrFile', wintypes.LPWSTR),
                    ('nMaxFile', wintypes.DWORD),
                    ('lpstrFileTitle', wintypes.LPWSTR),
                    ('nMaxFileTitle', wintypes.DWORD),
                    ('lpstrInitialDir', wintypes.LPCWSTR),
                    ('lpstrTitle', wintypes.LPCWSTR),
                    ('Flags', wintypes.DWORD),
                    ('nFileOffset', wintypes.WORD),
                    ('nFileExtension', wintypes.WORD),
                    ('lpstrDefExt', wintypes.LPCWSTR),
                    ('lCustData', wintypes.LPARAM),
                    ('lpfnHook', wintypes.LPVOID),
                    ('lpTemplateName', wintypes.LPCWSTR),
                    ('pvReserved', wintypes.LPVOID),
                    ('dwReserved', wintypes.DWORD),
                    ('FlagsEx', wintypes.DWORD)]

    # Filter: Paare aus Beschriftung und Muster, mit \0 getrennt, \0\0 am Ende.
    parts = []
    for ft in file_types:
        label, _, pat = ft.partition('(')
        pat = pat.rstrip(')').strip() or '*.*'
        parts += [label.strip() or pat, pat]
    filt = '\0'.join(parts) + '\0\0'

    buf = ctypes.create_unicode_buffer(default_name, 4096)
    ofn = OPENFILENAME()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAME)
    ofn.hwndOwner = None
    ofn.lpstrFilter = filt
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = 4096
    ofn.lpstrTitle = 'Kurs speichern' if save else 'Kurs wählen'
    OFN_EXPLORER, OFN_FILEMUSTEXIST, OFN_OVERWRITEPROMPT = 0x00080000, 0x00001000, 0x00000002
    OFN_PATHMUSTEXIST, OFN_NOCHANGEDIR = 0x00000800, 0x00000008
    ofn.Flags = OFN_EXPLORER | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | (
        OFN_OVERWRITEPROMPT if save else OFN_FILEMUSTEXIST)

    dll = ctypes.windll.comdlg32
    ok = dll.GetSaveFileNameW(ctypes.byref(ofn)) if save else dll.GetOpenFileNameW(ctypes.byref(ofn))
    if not ok:
        # 0 heißt abgebrochen ODER Fehler — nur letzteres ist berichtenswert.
        err = dll.CommDlgExtendedError()
        if err:
            raise OSError(f'CommDlgExtendedError {err}')
        return None
    return buf.value or None


def _win_dialog_powershell(save, file_types, default_name=''):
    """Rückfallweg: WinForms-Dialog in einem eigenen Prozess (STA-Thread).

    Nur noch Ersatz, falls der Systemaufruf scheitert. Dynamische Werte kommen
    per Umgebungsvariable, nicht als Text im Befehl (keine Injektion).
    """
    if save:
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d=New-Object System.Windows.Forms.SaveFileDialog;"
              "$d.OverwritePrompt=$true;$d.FileName=$env:ATS_DLG_DEFNAME;")
    else:
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d=New-Object System.Windows.Forms.OpenFileDialog;"
              "$d.Multiselect=$false;")
    ps += ("$d.Filter=$env:ATS_DLG_FILTER;$d.RestoreDirectory=$true;"
           "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
           "{[Console]::Out.Write($d.FileName)}")
    env = dict(os.environ,
               ATS_DLG_FILTER=_winforms_filter(file_types),
               ATS_DLG_DEFNAME=default_name)
    out = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-Command', ps],
        capture_output=True, text=True, timeout=600, env=env,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return (out.stdout or '').strip() or None


def _win_file_dialog(save, file_types, default_name=''):
    """Windows-Dateidialog. Erst der Systemaufruf, dann der Ersatzweg.

    Scheitern BEIDE, wird das gemeldet statt verschluckt — ein stiller
    Fehlschlag sah für den Benutzer aus wie eine hängende App.

    Warum nicht ``window.create_file_dialog``? pywebview 6.2.1 (winforms) ruft
    ``ShowDialog(form)`` OHNE Marshalling auf den GUI-Thread auf. WinForms-
    Dialoge haben Thread-Affinität; der Aufruf aus einem Worker-Thread hängt
    mit eingebettetem WebView2 die Nachrichtenschleife auf.
    """
    try:
        return _win_dialog_ctypes(save, file_types, default_name)
    except Exception:
        _log_err('win_file_dialog/ctypes')
    return _win_dialog_powershell(save, file_types, default_name)


# --------------------------------------------------------------------------- API
class Api:
    """window.pywebview.api — für Aktionen (Dateiwahl, Export). Bilder laufen
    über den HTTP-Server, nicht über diese Brücke."""

    def __init__(self):
        self.window = None
        self.ats_path = None
        self.tpl_path = find_default_template()
        self._full = []    # index-1 -> PNG-Bytes der imc-Vorschau | None
        self._meta = []

    # -- Dateiauswahl -------------------------------------------------------
    def pick_ats(self):
        """Nicht-blockierend: Dialog + Analyse laufen in einem Thread, das
        Ergebnis wird per ``window.onPicked(data)`` an JS gepusht.

        Ein SYNCHRONER create_file_dialog aus dem js_api-Worker-Thread blockiert
        auf Windows/WebView2 die Message-Loop, die der native Dialog selbst
        braucht → die App geht in 'not responding'. Auf macOS/Cocoa toleriert.
        """
        threading.Thread(target=self._pick_and_analyze, daemon=True).start()
        return None

    def _pick_and_analyze(self):
        try:
            types = ('imc Content Studio Kurs (*.ats)', 'Alle Dateien (*.*)')
            if os.name == 'nt':
                try:
                    picked = _win_file_dialog(False, types)
                except Exception as e:
                    # Vorher fiel das auf None zurück — für die Oberfläche
                    # nicht von „abgebrochen" zu unterscheiden. Die App sah
                    # dann aus, als reagiere sie nicht.
                    _log_err('pick_ats/dialog')
                    self._push('onPicked', dict(
                        error=f'Der Dateidialog konnte nicht geöffnet werden: {e}'))
                    return
                res = (picked,) if picked else None
            else:
                res = self.window.create_file_dialog(
                    webview.FileDialog.OPEN, allow_multiple=False, file_types=types)
            if not res:
                self._push('onPicked', None)   # abgebrochen
                return
            self.ats_path = res[0]
            self._push('onPicked', self.analyze())
        except Exception as e:
            _log_err('pick_ats')
            self._push('onPicked', dict(error=f'Fehler beim Laden: {e}'))

    def status(self):
        return dict(ocr_lang=ats2story.ocr_lang() or 'KEINE')

    def analyze(self):
        try:
            with zipfile.ZipFile(self.ats_path) as atsz:
                scenes = ats2story.walk_course(atsz)
        except Exception as e:
            return dict(error=f'Kann .ats nicht lesen: {e}')
        scene_count = len(scenes)
        self._full, self._meta = [], []
        idx = 0
        for sc in scenes:
            for s in sc['slides']:
                idx += 1
                png = None
                try:
                    png = ats2story.thumbnail(s['ata'])
                except Exception:
                    png = None
                self._full.append(png)
                # Fragen bekommen in der Vorschau eine TEXTdarstellung statt
                # eines Bildes — Frage, Optionen und Typ stehen im Depot des
                # Kurses und sind aussagekräftiger als das Vorschaubild.
                entry = dict(index=idx, scene=sc['name'],
                             name=s.get('name', 'Folie'),
                             quiz=bool(s.get('quiz') or s.get('exam')))
                if s.get('quiz') and s.get('ata'):
                    entry['q'] = self._question(s)
                self._meta.append(entry)
        # Erkannter imc-Canvas — dieselbe Größe, mit der später konvertiert wird.
        try:
            cw, ch = ats2story.detect_canvas(scenes)
            canvas = f'{cw}×{ch}'
        except Exception:
            canvas = None
        del scenes  # große .ata-Bytes freigeben
        return dict(file=os.path.basename(self.ats_path),
                    scenes=scene_count, slides=idx, canvas=canvas, list=self._meta)

    @staticmethod
    def _question(slide) -> dict | None:
        """Frage-Daten einer Quizfolie für die Textvorschau (oder None)."""
        try:
            items, _audio = ats2story.slide_content(slide['ata'])
            q = question_from_slide(slide.get('name', 'Frage'), items)
        except Exception:
            return None
        if not q:
            return None
        return dict(type=q['type'], text=q['text'],
                    options=[[t, bool(c)] for t, c in q['options']])

    def full(self, i):
        i -= 1
        return self._full[i] if 0 <= i < len(self._full) else None

    # -- Export -------------------------------------------------------------
    def export_story(self, opts):
        """Nicht-blockierend (wie ``pick_ats``): Save-Dialog + Konvertierung
        laufen in einem Thread, Ergebnis kommt per ``window.onExported(r)``.
        Verhindert den Windows/WebView2-Deadlock des synchronen Dialogs."""
        threading.Thread(target=self._export, args=(opts or {},), daemon=True).start()
        return None

    def _export(self, opts):
        try:
            if not self.ats_path:
                self._push('onExported', dict(ok=False, msg='Keine .ats-Datei gewählt.'))
                return
            if not self.tpl_path or not os.path.isfile(self.tpl_path):
                self._push('onExported', dict(ok=False,
                           msg='Internes Storyline-Grundgerüst nicht gefunden (Installation beschädigt?).'))
                return

            default_name = os.path.splitext(os.path.basename(self.ats_path))[0] + '.story'
            if os.name == 'nt':
                picked = _win_file_dialog(True, ('Articulate Storyline (*.story)',), default_name)
                res = (picked,) if picked else None
            else:
                res = self.window.create_file_dialog(
                    webview.FileDialog.SAVE, save_filename=default_name,
                    file_types=('Articulate Storyline (*.story)',))
            if not res:
                self._push('onExported', dict(ok=False, msg='Export abgebrochen.'))
                return
            out = res if isinstance(res, str) else res[0]
            if not out.lower().endswith('.story'):
                out += '.story'

            lang = opts.get('ocr_lang')
            if lang:
                if lang not in _ALLOWED_LANGS:
                    self._push('onExported', dict(ok=False, msg=f'Ungültige OCR-Sprache: {lang!r}.'))
                    return
                _ocr_config.OCR_LANG_PREF = lang
                _ocr_config.reset_lang_cache()

            def prog(frac, msg):
                self._push('onProgress', float(frac), str(msg))

            stats = ats2story.convert_ats(
                self.ats_path, out, tpl=self.tpl_path,
                ocr_text=bool(opts.get('ocr', True)),
                no_audio=not bool(opts.get('audio', True)),
                single_scene=bool(opts.get('single_scene', False)),
                no_exams=bool(opts.get('no_exams', True)),
                clean_bg=bool(opts.get('clean_bg', True)),
                course_bg=bool(opts.get('course_bg', True)),
                quiz_export=bool(opts.get('quiz_export', False)),
                quiz_slides=bool(opts.get('quiz_slides', False)),
                quiz_bank=bool(opts.get('quiz_bank', True)),
                quiz_font_pt=_quiz_font_of(opts),
                geometry=_geometry_of(opts),
                progress=prog)
            self._push('onExported', dict(ok=True, out=out, **{k: stats[k] for k in
                       ('slides', 'scenes', 'media', 'size', 'ocr_replaced', 'ocr_conf', 'bad',
                        'skipped_imgs', 'skipped_slides', 'skipped_audio', 'ocr_errors',
                        'skipped_detail', 'quiz_files', 'bank_slides',
                        'bank_skipped')}))
        except Exception as e:
            _log_err('export_story')
            self._push('onExported', dict(ok=False, msg=f'Fehler bei der Konvertierung: {e}'))

    def reveal(self, path):
        """Exportierte Datei im Finder/Explorer zeigen (plattformübergreifend)."""
        try:
            if not path or not os.path.exists(path):
                return dict(ok=False)
            if sys.platform == 'darwin':
                subprocess.run(['open', '-R', path], check=False)
            elif os.name == 'nt':
                subprocess.run(['explorer', '/select,', os.path.normpath(path)], check=False)
            else:
                subprocess.run(['xdg-open', os.path.dirname(path) or '.'], check=False)
            return dict(ok=True)
        except Exception:
            return dict(ok=False)

    def _push(self, fn, *args):
        try:
            payload = ', '.join(json.dumps(a) for a in args)
            self.window.evaluate_js(f'window.{fn} && window.{fn}({payload})')
        except Exception:
            pass


# --------------------------------------------------------------------------- HTTP
def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            try:
                with open(_ACCESS_LOG, 'a') as f:
                    f.write('%s %s\n' % (self.log_date_time_string(), fmt % args))
            except Exception:
                pass

        def _send(self, data, ctype, code=200):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except Exception:
                pass

        def _static(self, name, ctype):
            try:
                with open(os.path.join(WEB_DIR, name), 'rb') as f:
                    self._send(f.read(), ctype)
            except Exception:
                self._send(b'not found', 'text/plain', 404)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path in ('/', '/index.html'):
                return self._static('index.html', 'text/html; charset=utf-8')
            if path == '/style.css':
                return self._static('style.css', 'text/css')
            if path == '/app.js':
                return self._static('app.js', 'application/javascript')
            if path.startswith('/full/'):
                try:
                    i = int(path.rpartition('/')[2])
                except ValueError:
                    return self._send(b'bad', 'text/plain', 400)
                data = api.full(i)
                if not data:
                    return self._send(b'no image', 'text/plain', 404)
                return self._send(data, 'image/png')
            return self._send(b'not found', 'text/plain', 404)
    return Handler


def main():
    configure_bundled_ocr()
    try:
        with open(_ACCESS_LOG, 'w'):  # Log pro Lauf frisch
            pass
    except Exception:
        pass
    # Die App startet IMMER ohne geladenen Kurs. Früher konnte eine Umgebungs-
    # variable (ATS_DEBUG_FILE) beim Start eine Datei vorladen — das ist als
    # Entwicklungs-Abkürzung praktisch, überrascht aber jeden, der die App
    # normal benutzt, und war auch nicht abschaltbar, sobald die Variable in
    # der Umgebung stand. Zum Testen: Kurs im Dialog wählen.
    api = Api()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(api))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f'[ATS-App] HTTP-Server auf 127.0.0.1:{port}  ·  Zugriffslog: {_ACCESS_LOG}')

    window = webview.create_window(
        'ATS → Storyline Converter',
        url=f'http://127.0.0.1:{port}/',
        js_api=api, width=1080, height=760, min_size=(820, 600))
    api.window = window
    webview.start(debug=bool(os.environ.get('ATS_APP_DEBUG')))


if __name__ == '__main__':
    main()
