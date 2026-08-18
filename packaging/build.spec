# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller-Spec für den ATS → Storyline Converter (macOS .app).

Bündelt: App (converter_app/app.py) + web/ + Engine (ats2story-Paket) +
eingebautes Storyline-Grundgerüst + Tesseract-Binary (inkl. dylibs) + tessdata.

Build:  bash packaging/build_macos.sh   (stuft tessdata vor und ruft das hier auf)
"""
import os
import shutil
import sys

IS_MAC = sys.platform == 'darwin'
ROOT = os.path.dirname(SPECPATH)                      # Projektwurzel (SPECPATH = packaging/)
APP_ENTRY = os.path.join(ROOT, 'converter_app', 'app.py')
SKELETON = os.path.join(ROOT, 'ats2story', 'assets', 'skeleton.story')
STAGE_TESSDATA = os.path.join(SPECPATH, '_tessdata_stage')

# Tesseract-Binary (aufgelöster echter Pfad) — dessen dylib-Abhängigkeiten
# zieht PyInstaller automatisch mit (otool-Analyse) und verbiegt die Ladepfade.
_tess = shutil.which('tesseract') or (
    r'C:\Program Files\Tesseract-OCR\tesseract.exe' if os.name == 'nt'
    else '/opt/homebrew/bin/tesseract')
if not os.path.isfile(_tess):
    # Frueher lief der Build durch und die fertige App konnte einfach keinen
    # Text erkennen — der Fehler zeigte sich erst beim Benutzer.
    raise SystemExit(
        f'Tesseract nicht gefunden ({_tess}). Es wird MIT in die App gepackt, '
        'muss zum Bauen also vorhanden sein:\n'
        '  macOS:   brew install tesseract tesseract-lang\n'
        '  Windows: choco install tesseract')
TESS_BIN = os.path.realpath(_tess)

datas = [
    (os.path.join(ROOT, 'converter_app', 'web'), 'web'),
    (SKELETON, os.path.join('ats2story', 'assets')),
    (STAGE_TESSDATA, 'tessdata'),
]
binaries = [(TESS_BIN, 'tesseract')]
if os.name == 'nt':
    # Windows sucht die DLLs eines Programms ZUERST in dessen eigenem Ordner.
    # tesseract.exe landet unter tesseract/ — lägen libtesseract & Co. wie
    # üblich im Wurzelverzeichnis der App, fände die exe sie dort nicht und
    # startete gar nicht. Deshalb kommt der komplette Inhalt des
    # Installationsordners daneben. (Auf macOS erledigt PyInstaller das über
    # die otool-Analyse samt Umbiegen der Ladepfade.)
    _tess_dir = os.path.dirname(TESS_BIN)
    for _f in os.listdir(_tess_dir):
        if _f.lower().endswith('.dll'):
            binaries.append((os.path.join(_tess_dir, _f), 'tesseract'))
hiddenimports = [
    'webview', 'PIL', 'PIL.Image', 'PIL.ImageFile',
    'defusedxml', 'defusedxml.ElementTree', 'lameenc',
]

# Auf Windows zeigt pywebview seine Oberfläche über WinForms, und das läuft
# über .NET: pythonnet lädt Python.Runtime.dll, clr_loader bringt die
# zugehörigen nativen Teile mit. PyInstaller findet nichts davon von selbst —
# es sind keine Importe, sondern Beigaben der Pakete. Ohne sie startete die
# fertige App gar nicht:
#   Failed to resolve Python.Runtime.Loader.Initialize
if os.name == 'nt':
    from PyInstaller.utils.hooks import collect_all
    for _pkg in ('pythonnet', 'clr_loader'):
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    hiddenimports += ['clr', 'webview.platforms.winforms', 'webview.platforms.edgechromium']

a = Analysis(
    [APP_ENTRY],
    pathex=[ROOT],                       # damit `import ats2story` gefunden wird
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy.testing'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='ATS Converter',
    console=False,                       # GUI-App (kein Terminalfenster)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # Signierung nur, wenn CODESIGN_IDENTITY gesetzt ist (build_macos.sh). PyInstaller
    # signiert dann inside-out (dylibs + Tesseract einzeln, Hardened Runtime automatisch).
    # ACHTUNG: bei Spec-Builds wird das CLI-Flag --codesign-identity ignoriert — nur so.
    codesign_identity=os.environ.get('CODESIGN_IDENTITY') or None,
    entitlements_file=(os.path.join(SPECPATH, 'entitlements.plist')
                       if os.environ.get('CODESIGN_IDENTITY') else None),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name='ATS Converter',
)
# BUNDLE (.app) gibt es nur auf macOS; auf Windows/Linux ist das COLLECT-Verzeichnis
# (dist/ATS Converter/ATS Converter[.exe]) das Ergebnis.
if IS_MAC:
    app = BUNDLE(
        coll,
        name='ATS Converter.app',
        icon=None,
        bundle_identifier='com.ebcl.ats2story',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleDisplayName': 'ATS → Storyline Converter',
            'CFBundleShortVersionString': os.environ.get('APP_VERSION', '1.0.0'),
            'CFBundleVersion': os.environ.get('BUILD_NUMBER', '1'),
            'LSMinimumSystemVersion': '11.0',
        },
    )
