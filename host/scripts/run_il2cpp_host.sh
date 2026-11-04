#!/usr/bin/env bash
# Run the il2cpp standalone host on a device and print the fault backtrace.
#
# Env: SER (adb serial), DIR (device dir with libs+metadata), ARGS (extra args).
set -uo pipefail
export MSYS_NO_PATHCONV=1
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-10CEB60NHS001DX}"
DIR="${DIR:-/data/local/tmp/gc_transplant}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]")/../.." && pwd -W 2>/dev/null || pwd)"

"$ADB" -s "$SER" push "$ROOT/host/build/il2cpp_host" "$DIR/il2cpp_host" >/dev/null
"$ADB" -s "$SER" shell "chmod 755 $DIR/il2cpp_host; cd $DIR && timeout 180 ./il2cpp_host $DIR ${ARGS:-} > $DIR/ih.log 2>&1; echo rc=\$?"
"$ADB" -s "$SER" shell "sed -n '/FAULT/,\$p' $DIR/ih.log | head -40"
