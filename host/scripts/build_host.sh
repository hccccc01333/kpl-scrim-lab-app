#!/usr/bin/env bash
# build_host.sh — build host/src/gchost.c for Android ARM64 with NDK r28b.
#
# Overridable environment:
#   NDK / ANDROID_NDK_HOME / ANDROID_NDK_ROOT  Android NDK root
#   API        Android API level (default: 28)
#   SRC        source file (default: <repo>/host/src/gchost.c)
#   OUT_DIR    output directory (default: <repo>/host/build)
#   OUT_BIN    output binary (default: $OUT_DIR/gchost)
#
# The script only builds. It does not touch a device, the game, or game files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -W 2>/dev/null || pwd)"
SRC="${SRC:-$ROOT/host/src/gchost.c}"
OUT_DIR="${OUT_DIR:-$ROOT/host/build}"
OUT_BIN="${OUT_BIN:-$OUT_DIR/gchost}"
API="${API:-28}"

log() { printf '[build_host] %s\n' "$*"; }
die() { printf '[build_host] E: %s\n' "$*" >&2; exit 1; }

host_tag() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) printf 'windows-x86_64\n' ;;
        Darwin)               printf 'darwin-x86_64\n' ;;
        Linux)                printf 'linux-x86_64\n' ;;
        *)                    return 1 ;;
    esac
}

ndk_ok() {
    local d="${1:-}"
    [ -n "$d" ] && [ -d "$d/toolchains/llvm/prebuilt" ]
}

resolve_ndk() {
    local d="${1:-}"
    [ -n "$d" ] || return 1
    if ndk_ok "$d"; then
        printf '%s\n' "$d"
        return 0
    fi
    # Tolerate an archive extracted into an extra directory level, e.g.
    # <dir>/android-ndk-r28b/<actual NDK>.
    local nested
    for nested in "$d"/android-ndk-r* "$d"/ndk-r*; do
        [ -d "$nested" ] || continue
        if ndk_ok "$nested"; then
            printf '%s\n' "$nested"
            return 0
        fi
    done
    return 1
}

[ -f "$SRC" ] || die "source not found: $SRC"

HOST_TAG="$(host_tag)" || die "unsupported host platform: $(uname -s)"

candidates=()
[ -n "${NDK:-}" ] && candidates+=("$NDK")
[ -n "${ANDROID_NDK_HOME:-}" ] && candidates+=("$ANDROID_NDK_HOME")
[ -n "${ANDROID_NDK_ROOT:-}" ] && candidates+=("$ANDROID_NDK_ROOT")

# Android SDK-managed NDKs (portable glob; no GNU find -maxdepth).
for sdk in \
    "${ANDROID_HOME:-}" \
    "${ANDROID_SDK_ROOT:-}" \
    "$HOME/Android/Sdk" \
    "$HOME/Library/Android/sdk" \
    "${LOCALAPPDATA:-}/Android/Sdk"; do
    [ -n "$sdk" ] && [ -d "$sdk/ndk" ] || continue
    for d in "$sdk"/ndk/*/; do
        d="${d%/}"
        [ -d "$d" ] && candidates+=("$d")
    done
done

# Common standalone/archive locations.
for base in "$HOME" /opt /usr/local; do
    for d in "$base"/android-ndk* "$base"/ndk-r*; do
        [ -d "$d" ] && candidates+=("$d")
    done
done

# Git Bash/MSYS exposes drives as mount points (/c, /d, ...). Root-level globs
# such as /*/android-ndk* are not expanded there, so use /proc/mounts.
if [ -r /proc/mounts ]; then
    while read -r _src mnt _fstype _rest; do
        case "$mnt" in
            /[a-zA-Z]) ;;
            *) continue ;;
        esac
        for d in "$mnt"/android-ndk* "$mnt"/ndk-r*; do
            [ -d "$d" ] && candidates+=("$d")
        done
    done < /proc/mounts
fi

# Native Linux: also allow one extra level under the filesystem root.
for d in /*/android-ndk* /*/ndk-r*; do
    [ -d "$d" ] && candidates+=("$d")
done

NDK_RESOLVED=""
for d in "${candidates[@]}"; do
    if resolved="$(resolve_ndk "$d")"; then
        NDK_RESOLVED="$resolved"
        break
    fi
done
[ -n "$NDK_RESOLVED" ] || die "Android NDK not found; set NDK=/path/to/android-ndk-r28b"

TOOLCHAIN="$NDK_RESOLVED/toolchains/llvm/prebuilt/$HOST_TAG"
CC="$TOOLCHAIN/bin/aarch64-linux-android${API}-clang"
[ -d "$TOOLCHAIN" ] || die "NDK has no $HOST_TAG toolchain: $TOOLCHAIN"
[ -x "$CC" ] || die "compiler not found or not executable: $CC (API=$API)"

mkdir -p "$OUT_DIR"

log "NDK:     $NDK_RESOLVED"
log "host:    $HOST_TAG (API $API)"
log "source:  $SRC"
log "output:  $OUT_BIN"

# -fPIE -pie -O2 -ldl are required by the harness contract.
"$CC" \
    -std=c11 \
    -fPIE -pie \
    -O2 \
    -Wall -Wextra \
    -D_GNU_SOURCE \
    -o "$OUT_BIN" \
    "$SRC" \
    -ldl

[ -s "$OUT_BIN" ] || die "compiler produced no output: $OUT_BIN"
log "built:   $OUT_BIN ($(wc -c < "$OUT_BIN" | tr -d ' ') bytes)"
log "ARM64 check:"
"$TOOLCHAIN/bin/llvm-readelf" -h "$OUT_BIN" | grep -E 'Class:|Machine:|Type:' || true
