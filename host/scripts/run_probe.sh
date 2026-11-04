#!/usr/bin/env bash
# GameCore host probe runner (H0/H1/H2).
# Runs a private ARM64 host process on MuMu; never attaches to the game process.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || pwd)"
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-127.0.0.1:16384}"
SRC="$ROOT/data/replays/_analysis/_host"
AN="$ROOT/data/replays/_analysis"
BLOCKS="$AN/device/dtab_blocks"
MODE="${1:-boot}"
DEV=/data/local/tmp/gc

"$ADB" connect "$SER" >/dev/null 2>&1 || true
"$ADB" -s "$SER" shell "id -u" | grep -qx 0 || {
  "$ADB" -s "$SER" root
  sleep 1
}

"$ADB" -s "$SER" shell "mkdir -p $DEV/dtab_blocks"

push_lib() {
  local name="$1"
  local src="$2"
  [ -f "$src" ] || { echo "missing $src" >&2; exit 10; }
  "$ADB" -s "$SER" push "$src" "$DEV/$name" >/dev/null
}

for name in libpandora.so libpixuiCurl.so libPixUI_Unity.so libpuerts.so; do
  push_lib "$name" "$SRC/libs/$name"
done
push_lib libGameCore.so "$AN/libGameCore.so"

case "$MODE" in
  boot)
    push_lib gc_boot "$SRC/gc_boot"
    "$ADB" -s "$SER" shell "chmod 755 $DEV/gc_boot; cd $DEV && ./gc_boot --init --keepalive 5"
    ;;
  sim0)
    push_lib gc_sim0 "$SRC/gc_sim0"
    push_lib dtab_blocks/83_svr2GamecoreCfg.bytes.bin \
      "$BLOCKS/83_svr2GamecoreCfg.bytes.bin"
    "$ADB" -s "$SER" shell "chmod 755 $DEV/gc_sim0; cd $DEV && ./gc_sim0"
    ;;
  sim0b)
    push_lib gc_sim0b "$SRC/gc_sim0b"
    "$ADB" -s "$SER" push "$BLOCKS/." "$DEV/dtab_blocks/" >/dev/null
    "$ADB" -s "$SER" shell "chmod 755 $DEV/gc_sim0b; cd $DEV && ./gc_sim0b"
    ;;
  *)
    echo "usage: $0 boot|sim0|sim0b" >&2
    exit 2
    ;;
esac
