#!/usr/bin/env bash
# Install the official PrusaSlicer macOS release and give it a minimal throwaway data directory, so the
# integration tests can run on a machine that has never seen PrusaSlicer.
#
# usage: setup-prusaslicer-macos.sh <version> <workdir>
#
# Prusa stopped attaching Linux builds to its GitHub releases after 2.8.x, so CI uses macOS, which also matches
# the version this project is developed against. The data directory is built from the profiles that ship inside
# the app (Prusa's profile data is AGPL, so it is never committed to this repository).
set -euo pipefail

version="${1:?usage: setup-prusaslicer-macos.sh <version> <workdir>}"
work="${2:?usage: setup-prusaslicer-macos.sh <version> <workdir>}"

mkdir -p "$work"
dmg="$work/PrusaSlicer-$version.dmg"
# CI caches this file keyed by version (see ci.yml), so a cache hit means no download at all.
if [ -f "$dmg" ]; then
  echo "using the already downloaded $dmg" >&2
else
  curl --fail --location --silent --show-error --output "$dmg" \
    "https://github.com/prusa3d/PrusaSlicer/releases/download/version_${version}/PrusaSlicer-${version}.dmg"
fi

mount="$work/mnt"
mkdir -p "$mount"
hdiutil attach "$dmg" -mountpoint "$mount" -nobrowse -readonly -quiet
trap 'hdiutil detach "$mount" -quiet || true' EXIT

# The app sits one folder down ("Original Prusa Drivers/PrusaSlicer.app"), next to the printer drivers.
source_app="$(find "$mount" -maxdepth 2 -name 'PrusaSlicer.app' | head -n 1)"
[ -n "$source_app" ] || { echo "PrusaSlicer.app not found inside $dmg" >&2; exit 1; }
app="$work/PrusaSlicer.app"
rm -rf "$app"
cp -R "$source_app" "$app"

hdiutil detach "$mount" -quiet
trap - EXIT

# "Installed" printers are just a [vendor:...] section in PrusaSlicer.ini plus the vendor bundle. One printer
# (the MINI Input Shaper, 0.4 mm nozzle) is enough for every integration test.
datadir="$work/datadir"
rm -rf "$datadir"
mkdir -p "$datadir/vendor"
cp "$app/Contents/Resources/profiles/PrusaResearch.ini" "$datadir/vendor/"
printf '[vendor:PrusaResearch]\nmodel:MINIIS = 0.4\n' > "$datadir/PrusaSlicer.ini"

executable="$app/Contents/MacOS/PrusaSlicer"
if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "PRUSASLICER_PATH=$executable"
    echo "PRUSASLICER_DATADIR=$datadir"
  } >> "$GITHUB_ENV"
else
  echo "export PRUSASLICER_PATH='$executable'"
  echo "export PRUSASLICER_DATADIR='$datadir'"
fi
