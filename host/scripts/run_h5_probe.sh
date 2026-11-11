#!/usr/bin/env bash
# H5 probe: push real `.abc` frame payloads into CS slot0 and call the real
# GameCore CS consumer (`base+0x46B80E8`) in a private host process.
#
# Usage:
#   bash host/scripts/run_h5_probe.sh [probe args...]
#
# Examples:
#   bash host/scripts/run_h5_probe.sh --mode isolated --limit 20 --skip-empty
#   bash host/scripts/run_h5_probe.sh --mode sequential --start 3 --limit 5
#   bash host/scripts/run_h5_probe.sh --no-consumer --limit 3
#
# Environment overrides: ADB, SER, DEV, SNAP, FRAMES_DIR, CMD_TABLE, CTX,
# CONSUMER, CORE_STATE, OLD_BASE, REBUILD=1, EXTRACT=1, PUSH_SNAPSHOT=0.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || pwd)"
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-127.0.0.1:16384}"
DEV="${DEV:-/data/local/tmp/gc_transplant}"
SNAP="${SNAP:-$ROOT/data/replays/_analysis/client_probe_20261103/process_snapshot_2052}"
FRAMES_DIR="${FRAMES_DIR:-$ROOT/host/build/frames/20261102_161129}"
CMDTAB="${CMDTAB:-$ROOT/host/fixtures/20261102_161129/consumer/cmd_table.bin}"
CTX="${CTX:-0x75d7e86e9ff0}"
BINDER="${BINDER:-0x75d7ea4e99f0}"
CONSUMER="${CONSUMER:-0x75dc98daac10}"
CORE_STATE="${CORE_STATE:-0x400000000002}"
OLD_BASE="${OLD_BASE:-0x400036a00000}"
ABC="${ABC:-$ROOT/data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc}"
BIN="$ROOT/host/build/h5_probe"

[ -f "$ABC" ] || { echo "missing .abc: $ABC" >&2; exit 10; }
[ -f "$SNAP/regions.tsv" ] || { echo "missing snapshot: $SNAP" >&2; exit 11; }

if [ "${REBUILD:-0}" = 1 ] || [ ! -x "$BIN" ]; then
  NDK="${NDK:-/d/android-ndk-r28b}" \
  SRC="$ROOT/host/src/h5_probe.c" OUT_BIN="$BIN" \
    bash "$ROOT/host/scripts/build_host.sh"
fi

if [ "${EXTRACT:-0}" = 1 ] || [ ! -f "$FRAMES_DIR/index.tsv" ]; then
  python "$ROOT/host/scripts/extract_frame_payloads.py" "$ABC" --out-dir "$FRAMES_DIR" >/dev/null
fi

"$ADB" connect "$SER" >/dev/null 2>&1 || true
"$ADB" -s "$SER" root >/dev/null 2>&1 || true
sleep 1

"$ADB" -s "$SER" shell "mkdir -p $DEV/snapshot $DEV/frames"
"$ADB" -s "$SER" push "$BIN" "$DEV/h5_probe" >/dev/null
"$ADB" -s "$SER" push "$FRAMES_DIR/." "$DEV/frames/" >/dev/null
if [ -f "$CMDTAB" ]; then
  "$ADB" -s "$SER" push "$CMDTAB" "$DEV/cmd_table.bin" >/dev/null
fi
if [ "${PUSH_SNAPSHOT:-1}" = 1 ]; then
  "$ADB" -s "$SER" push "$SNAP/." "$DEV/snapshot/" >/dev/null
fi
for n in libpandora.so libpixuiCurl.so libPixUI_Unity.so libpuerts.so; do
  [ -f "$ROOT/data/replays/_analysis/_host/libs/$n" ] || continue
  "$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/_host/libs/$n" "$DEV/$n" >/dev/null
done
[ -f "$ROOT/data/replays/_analysis/libGameCore.so" ] && \
  "$ADB" -s "$SER" push "$ROOT/data/replays/_analysis/libGameCore.so" "$DEV/libGameCore.so" >/dev/null

ARGS=(--lib-dir "$DEV" --snapshot "$DEV/snapshot" --frames "$DEV/frames"
      --old-base "$OLD_BASE" --context "$CTX" --binder "$BINDER" --consumer "$CONSUMER"
      --core-state "$CORE_STATE")
[ -f "$CMDTAB" ] && ARGS+=(--cmd-table "$DEV/cmd_table.bin")
if [ "$#" -eq 0 ]; then
  set -- --mode isolated --skip-empty
fi

"$ADB" -s "$SER" shell "chmod 755 $DEV/h5_probe; cd $DEV && ./h5_probe ${ARGS[*]} $*"
