#!/usr/bin/env bash
# Baut die macOS-.app des ATS → Storyline Converters (unsigniert).
#   Voraussetzung: brew tesseract + tesseract-lang, python3, pyinstaller, pywebview, Pillow, defusedxml
#   Aufruf:  bash packaging/build_macos.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

# 1) tessdata vorstufen: deu/pol aus tessdata_best (bessere Erkennung,
#    langsamer — Timeout in der Engine ist entsprechend erhöht), eng aus der
#    lokalen Installation. osd wird NICHT mehr gestaged (psm 3 braucht kein OSD).
STAGE="$HERE/_tessdata_stage"
CACHE="$HERE/_tessdata_best_cache"
rm -rf "$STAGE"; mkdir -p "$STAGE" "$CACHE"
SRC="/opt/homebrew/share/tessdata"
for L in deu pol; do
  if [ ! -s "$CACHE/$L.traineddata" ]; then
    echo "[build] lade tessdata_best/$L.traineddata ..."
    curl -fL -o "$CACHE/$L.traineddata" \
      "https://github.com/tesseract-ocr/tessdata_best/raw/main/$L.traineddata"
  fi
  cp "$CACHE/$L.traineddata" "$STAGE/"
done
if [ -e "$SRC/eng.traineddata" ]; then
  cp -L "$SRC/eng.traineddata" "$STAGE/"
else
  echo "WARN: eng.traineddata nicht gefunden in $SRC"
fi
echo "[build] tessdata gestaged: $(ls "$STAGE" | tr '\n' ' ')"

# 2) PyInstaller
rm -rf "$ROOT/build" "$ROOT/dist"
python3 -m PyInstaller --noconfirm --clean "$HERE/build.spec" \
  --distpath "$ROOT/dist" --workpath "$ROOT/build"

APP="$ROOT/dist/ATS Converter.app"
echo ""
echo "[build] .app gebaut → $APP"

# 3) Signieren + Notarisieren — NUR wenn CODESIGN_IDENTITY gesetzt ist.
#    PyInstaller hat in Schritt 2 bereits inside-out signiert (dylibs + Tesseract
#    + .app, Hardened Runtime + Entitlements), sofern CODESIGN_IDENTITY in der
#    Umgebung war. Hier folgt Preflight + Notarisierung + Verteil-DMG.
if [ -z "${CODESIGN_IDENTITY:-}" ]; then
  echo "[build] UNSIGNIERT (CODESIGN_IDENTITY nicht gesetzt)."
  echo "[build] Start:   open \"$APP\""
  exit 0
fi

VERSION="${APP_VERSION:-1.0.0}"
AC_KEY="${AC_KEY:-$HOME/.appstoreconnect/private_keys/AuthKey_7C67GYF3K6.p8}"
AC_KEY_ID="${AC_KEY_ID:-7C67GYF3K6}"
AC_ISSUER="${AC_ISSUER:-797425c3-e5e8-4192-a8e0-04afa61c9156}"

echo "[sign] Preflight-Verifikation ..."
codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dvv "$APP" 2>&1 | grep -Ei 'flags|Timestamp|Authority=Developer ID' || true

echo "[notarize] ZIP (via ditto, Symlink-erhaltend) ..."
ZIP="$ROOT/dist/ATS-Converter-notarize.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "[notarize] Upload an Apple (kann einige Minuten dauern) ..."
xcrun notarytool submit "$ZIP" --key "$AC_KEY" --key-id "$AC_KEY_ID" --issuer "$AC_ISSUER" --wait

echo "[notarize] Ticket an die .app staplen ..."
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl -a -t exec -vv "$APP" || true

echo "[dist] Verteil-DMG bauen ..."
DMG="$ROOT/dist/ATS-Converter-$VERSION.dmg"
rm -f "$DMG"
hdiutil create -volname "ATS Converter" -srcfolder "$APP" -ov -format UDZO "$DMG"
codesign --sign "$CODESIGN_IDENTITY" --timestamp "$DMG"
rm -f "$ZIP"

echo ""
echo "[build] ✅ SIGNIERT + NOTARISIERT → $DMG"
