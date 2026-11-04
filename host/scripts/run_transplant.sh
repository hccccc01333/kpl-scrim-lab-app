#!/usr/bin/env bash
# A1: run the context-transplant host against a captured process snapshot.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || pwd)"
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-127.0.0.1:16384}"
DEV=/data/local/tmp/gc_transplant
SNAP="${SNAP:-$ROOT/data/replays/_analysis/client_probe_20261103/process_snapshot_2052}"
CTX="${CTX:-0x75d7ea4e99f0}"   # true binder context P, inside context arena
CONSUMER="${CONSUMER:-0x75dc98daac10}"
CORE_STATE="${CORE_STATE:-0x400000000002}"
OLD_BASE="${OLD_BASE:-0x400036a00000}"

"$ADB" connect "$SER" >/dev/null 2>&1 || true
"$ADB" -s "$SER" root >/dev/null 2>&1 || true
sleep 1
"$ADB" -s "$SER" shell "mkdir -p $DEV/snapshot"
"$ADB" -s "$SER" push "$ROOT/host/build/gc_transplant" "$DEV/gc_transplant" >/dev/null
"$ADB" -s "$SER" push "$SNAP/." "$DEV/snapshot/" >/dev/null
for n in libpandora.so libpixuiCurl.so libPixUI_Unity.so libpuerts.so; do
  "$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/_host/libs/$n" "$DEV/$n" >/dev/null
done
"$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/libGameCore.so" "$DEV/libGameCore.so" >/dev/null

"$ADB" -s "$SER" shell "chmod 755 $DEV/gc_transplant; cd $DEV && ./gc_transplant $DEV/snapshot/regions.tsv $DEV/snapshot $OLD_BASE $CTX $CONSUMER $CORE_STATE"
