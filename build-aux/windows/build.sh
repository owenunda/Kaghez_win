#!/usr/bin/env bash
# Builds the Windows version of Kaghez.
#
# Run from the repository root inside an MSYS2 UCRT64 shell:
#   bash build-aux/windows/build.sh            # installs deps with pacman first
#   bash build-aux/windows/build.sh --no-deps  # deps already installed (CI)
#
# Result: _build-windows/dist/Kaghez/Kaghez.exe (portable folder). The
# installer is made afterwards from build-aux/windows/kaghez.iss with Inno
# Setup, which runs outside MSYS2.

set -euo pipefail

JRE_URL="https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"
SERVER_JAR="Suwayomi-Server-v2.3.2361.jar"

PACKAGES=(
  mingw-w64-ucrt-x86_64-python
  mingw-w64-ucrt-x86_64-python-gobject
  mingw-w64-ucrt-x86_64-python-pip
  mingw-w64-ucrt-x86_64-python-httpx
  mingw-w64-ucrt-x86_64-python-aiohttp
  mingw-w64-ucrt-x86_64-python-pillow
  mingw-w64-ucrt-x86_64-gtk4
  mingw-w64-ucrt-x86_64-libadwaita
  mingw-w64-ucrt-x86_64-librsvg
  mingw-w64-ucrt-x86_64-blueprint-compiler
  mingw-w64-ucrt-x86_64-meson
  mingw-w64-ucrt-x86_64-ninja
  mingw-w64-ucrt-x86_64-pkgconf
  mingw-w64-ucrt-x86_64-gettext-tools
  mingw-w64-ucrt-x86_64-desktop-file-utils
  mingw-w64-ucrt-x86_64-pyinstaller
  mingw-w64-ucrt-x86_64-pyinstaller-hooks-contrib
  unzip
)

if [[ "${1:-}" == "--print-packages" ]]; then
  echo "${PACKAGES[@]}"
  exit 0
fi

if [[ "${MSYSTEM:-}" != "UCRT64" ]]; then
  echo "Run this from an MSYS2 UCRT64 shell." >&2
  exit 1
fi

if [[ "${1:-}" != "--no-deps" ]]; then
  pacman -S --noconfirm --needed "${PACKAGES[@]}"
fi

# Not packaged by MSYS2. Both are pure Python.
python -m pip install --break-system-packages --disable-pip-version-check gql diskcache

ROOT="$(cygpath -m "$PWD")"
OUT="$ROOT/_build-windows"
PREFIX="$OUT/prefix"
PKGDATADIR="$PREFIX/share/kaghez"

# A Git LFS pointer is ~130 bytes; the real jar is ~180 MB.
if [[ $(stat -c %s "src/$SERVER_JAR") -lt 1000000 ]]; then
  echo "src/$SERVER_JAR is a Git LFS pointer. Run 'git lfs pull' first." >&2
  exit 1
fi

rm -rf "$OUT/build" "$PREFIX" "$OUT/dist" "$OUT/pyinstaller"
mkdir -p "$OUT"

echo "==> meson"
meson setup "$OUT/build" --prefix="$PREFIX" --buildtype=release
meson install -C "$OUT/build"

echo "==> GSettings schema"
# Compiled into its own folder; kaghez.in points GSETTINGS_SCHEMA_DIR at it.
mkdir -p "$PKGDATADIR/schemas"
glib-compile-schemas --strict --targetdir="$PKGDATADIR/schemas" data

echo "==> Java runtime"
JRE_ZIP="$OUT/jre.zip"
if [[ ! -f "$JRE_ZIP" ]]; then
  curl -fL --retry 3 -o "$JRE_ZIP" "$JRE_URL"
fi
rm -rf "$OUT/jre-unpacked"
unzip -q "$JRE_ZIP" -d "$OUT/jre-unpacked"
# The zip holds a single versioned folder (jdk-21.x.y+z-jre).
mv "$OUT"/jre-unpacked/*/ "$PKGDATADIR/jre"
rm -rf "$OUT/jre-unpacked"

echo "==> app icon"
ICON="$OUT/kaghez.ico"
rsvg-convert -w 256 -h 256 -o "$OUT/kaghez-256.png" \
  data/icons/hicolor/scalable/apps/com.rini.kaghez.svg
python - "$OUT/kaghez-256.png" "$ICON" <<'EOF'
import sys
from PIL import Image
Image.open(sys.argv[1]).save(sys.argv[2], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
EOF

echo "==> PyInstaller"
# PyInstaller names the exe after the script.
cp "$PREFIX/bin/kaghez" "$OUT/Kaghez.py"
KAGHEZ_PREFIX="$PREFIX" KAGHEZ_OUT="$OUT" \
  pyinstaller --noconfirm \
    --distpath "$OUT/dist" \
    --workpath "$OUT/pyinstaller" \
    build-aux/windows/kaghez.spec
cp -r "$PKGDATADIR/jre" "$OUT/dist/Kaghez/_internal/share/kaghez/jre"

echo
echo "Done: $OUT/dist/Kaghez/Kaghez.exe"
