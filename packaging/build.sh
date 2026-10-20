#!/usr/bin/env bash
# Build the double-clickable app for the computer this runs on:
#   macOS   -> dist/discoal Studio.app + dist/discoal-studio-<v>-macos-<arch>.dmg
#   Windows -> dist/discoal-studio/ + dist/discoal-studio-<v>-windows-x64-setup.exe (+ .zip)
#              (run from Git Bash; needs MinGW-w64 gcc and Inno Setup 6)
#   Linux   -> dist/discoal-studio/ + dist/discoal-studio-<v>-linux-<arch>.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  Darwin) OS=macos ;;
  *) OS=linux ;;
esac
EXE=discoal; EXTRA=()
if [[ $OS == windows ]]; then EXE=discoal.exe; EXTRA=(-static); CC=${CC:-gcc}; fi

echo "1/3  Compiling discoal for $OS (bundled source with the sweepPopn, recurrent-sweep and Windows fixes)"
rm -rf src/discoal_studio/bin && mkdir -p src/discoal_studio/bin
( cd src/discoal_studio/vendor/discoal && ${CC:-cc} -O3 -I. ${EXTRA[@]+"${EXTRA[@]}"} -o "../../bin/$EXE" \
    discoal_multipop.c discoalFunctions.c ranlibComplete.c alleleTraj.c ancestrySegment.c \
    ancestrySegmentAVL.c ancestryVerify.c activeSegment.c -lm -fcommon )

echo "2/3  Packaging with PyInstaller"
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/discoal_studio.spec

echo "3/3  Making the download file"
VERSION=$(python -c "import discoal_studio; print(discoal_studio.__version__)")
ARCH=$(uname -m)
case $OS in
  macos)
    OUT="dist/discoal-studio-$VERSION-macos-$ARCH.dmg"
    rm -f "$OUT"
    hdiutil create -volname "discoal Studio" -srcfolder "dist/discoal Studio.app" -ov -format UDZO "$OUT" >/dev/null
    ;;
  windows)
    ( cd dist && python -m zipfile -c "discoal-studio-$VERSION-windows-x64.zip" discoal-studio )
    ISCC=${ISCC:-"/c/Program Files (x86)/Inno Setup 6/ISCC.exe"}
    "$ISCC" //Q "//DMyVersion=$VERSION" packaging/windows/discoal-studio.iss
    OUT="dist/discoal-studio-$VERSION-windows-x64-setup.exe"
    ;;
  linux)
    OUT="dist/discoal-studio-$VERSION-linux-$ARCH.tar.gz"
    tar -C dist -czf "$OUT" discoal-studio
    ;;
esac
echo "Done: $OUT"
