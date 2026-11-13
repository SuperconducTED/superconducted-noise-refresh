#!/usr/bin/env bash
# Write one pinned ref of the engine's calibration archive to a directory.
#   scripts/export_archive.sh <clone of superconducted-noise-engine> <output directory> [ref]
# The default ref is the one the pilot in results/pilot was run against.
set -euo pipefail
engine="${1:?path to a clone of superconducted-noise-engine}"
out="${2:?output directory}"
ref="${3:-00c9a1c7229f2cf2488656575d2722c63ad8cdd5}"
git -C "$engine" fetch --quiet origin calibration-data
git -C "$engine" cat-file -e "${ref}^{commit}"
mkdir -p "$out"
git -C "$engine" archive "$ref" snapshots | tar -x -C "$out"
echo "$ref" > "$out/REF"
echo "exported $(find "$out/snapshots" -name '*.json' | wc -l) snapshot files at $ref"
