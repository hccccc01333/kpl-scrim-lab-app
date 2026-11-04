#!/usr/bin/env bash
# Run the built host harness (H0/H1/H2) on MuMu. Read-only wrt game files.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || pwd)"
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-127.0.0.1:16384}"
DEV=/data/local/tmp/gc
FIX="${FIX:-$ROOT/host/fixtures/20261102_161129}"
BLOCKS="${BLOCKS:-$ROOT/data/replays/_analysis/device/dtab_blocks}"
BIN="${BIN:-$ROOT/host/build/gchost}"

"$ADB" connect "$SER" >/dev/null 2>&1 || true
"$ADB" -s "$SER" root >/dev/null 2>&1 || true
sleep 1
"$ADB" -s "$SER" shell "mkdir -p $DEV/dtab_blocks $DEV/fixture"

for name in libpandora.so libpixuiCurl.so libPixUI_Unity.so libpuerts.so; do
  "$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/_host/libs/$name" "$DEV/$name" >/dev/null
done
"$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/libGameCore.so" "$DEV/libGameCore.so" >/dev/null
"$ADB" -s "$SER" push "$BIN" "$DEV/gchost" >/dev/null
"$ADB" -s "$SER" push "$FIX/." "$DEV/fixture/" >/dev/null
"$ADB" -s "$SER" push "$BLOCKS/." "$DEV/dtab_blocks/" >/dev/null

"$ADB" -s "$SER" shell "chmod 755 $DEV/gchost; cd $DEV && ./gchost --lib-dir $DEV --fixture $DEV/fixture --replay-id 20261102_161129 --databin-dir $DEV/dtab_blocks --verify samples"
