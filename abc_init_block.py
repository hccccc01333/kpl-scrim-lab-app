"""Locate the ``.abc`` init records: the KV array and the 443-byte scalar block.

Only ``replay_parser`` owns container layout; this module owns the two blocks
that sit between the header and the player blocks, because their offsets move
with the header length and their terminators differ by client build:

    kv_start        u16LE count, then count x 4 B {confType:u8, value:u16BE, pad:u8}
    scalar block    110 x u32 BE (440 B, big endian)
    terminator      1-3 bytes (``0a`` on some builds, ``00 00 0a`` on others)
    player block 0  camp=1, echo=1, 0x01, slot=0, 0x0000, entityId:u16BE

Because the terminator length varies, the block is pinned by anchor words that
hold across every 5v5 sample seen so far and confirmed by the player-block
signature.  No field is named here: the documented meanings live in
``README.md`` and only cover indices 1/2/67.
"""
from __future__ import annotations

import hashlib

KV_CONFTYPE_HEAD = bytes(range(1, 11))
SCALAR_COUNT = 110
SCALAR_BYTES = SCALAR_COUNT * 4
MIN_KV_COUNT, MAX_KV_COUNT = 30, 80

# Alignment anchors, not field names: these words are stable across the 5v5
# samples, so they distinguish the right byte offset from a plausible neighbour.
ANCHOR_WORDS = {0: 0, 2: 300, 3: 1000, 4: 7, 5: 5, 6: 2, 7: 10, 8: 5, 9: 1,
                10: 66, 11: 1000}
ANCHOR_MIN = 8

PLAYER_BLOCK0 = b"\x01\x01\x01\x00\x00\x00"
TERMINATORS = (b"\x0a", b"\x00\x0a", b"\x00\x00\x0a")

# Documented meanings only.  Everything else stays unnamed on purpose.
KNOWN_WORDS = {
    1: "modeWord",
    2: "initialGold",
    67: "serverTimeUnixSeconds",
}


def locate(data: bytes) -> dict | None:
    """Return the KV range, scalar block and terminator, or ``None``.

    ``None`` means "this build does not carry the 1..10 confType head", not
    "the file is broken": older containers have a different layout.
    """
    limit = min(len(data) - 64, 0x4000)
    best = None
    for at in range(0x100, limit):
        if any(data[at + 4 * step] != KV_CONFTYPE_HEAD[step] for step in range(10)):
            continue
        kv_start = at - 2
        if kv_start < 0:
            continue
        count = int.from_bytes(data[kv_start:kv_start + 2], "little")
        if not MIN_KV_COUNT <= count <= MAX_KV_COUNT:
            continue
        base = kv_start + 2 + count * 4
        for shift in range(-4, 9):
            start = base + shift
            end = start + SCALAR_BYTES
            if end + 1 > len(data):
                continue
            block = data[start:end]
            words = [int.from_bytes(block[i * 4:i * 4 + 4], "big")
                     for i in range(SCALAR_COUNT)]
            score = sum(1 for index, value in ANCHOR_WORDS.items()
                        if words[index] == value)
            if score < ANCHOR_MIN:
                continue
            probe = data[end:end + 12]
            offset = probe.find(PLAYER_BLOCK0)
            if offset < 0:
                continue
            terminator = data[end:end + offset]
            if terminator not in TERMINATORS:
                continue
            candidate = {
                "score": score,
                "anchorTotal": len(ANCHOR_WORDS),
                "kvStart": kv_start,
                "kvCount": count,
                "kvEnd": kv_start + 2 + count * 4,
                "scalarStart": start,
                "scalarEnd": end,
                "terminator": terminator.hex(),
                "playerBlockStart": end + offset,
                "scalarSha": hashlib.sha256(block).hexdigest(),
                "words": words,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
        if best is not None and best["score"] == len(ANCHOR_WORDS):
            break
    if best is not None:
        best["block"] = data[best["scalarStart"]:best["scalarEnd"]]
    return best


def kv_pairs(data: bytes, located: dict) -> dict[int, int]:
    """confType -> confValue for the ``svr2GamecoreCfg`` array."""
    pairs: dict[int, int] = {}
    base = located["kvStart"] + 2
    for index in range(located["kvCount"]):
        off = base + index * 4
        pairs[data[off]] = int.from_bytes(data[off + 1:off + 3], "big")
    return pairs


def server_stamp_from_name(stem: str) -> int | None:
    """The server unix timestamp carried by the replay file name.

    Names look like ``20260101_000000_1593860880_29_1790300977_<hash>``: several
    segments can be 10-digit numbers (relay entity, table ids), so the last
    plausible unix-time segment is the timestamp, not the first.
    """
    candidates = []
    for part in stem.split("_"):
        token = part.lstrip("-")
        if token.isdigit() and len(token) == 10:
            value = int(token)
            if 1_600_000_000 <= value <= 2_100_000_000:
                candidates.append(value)
    return candidates[-1] if candidates else None


def kv_ruleset_sha(pairs: dict[int, int]) -> str:
    """Stable fingerprint of the ``svr2GamecoreCfg`` rule set.

    All 14 supported 5v5 samples carry byte-identical KV values, so this hash
    identifies the ruleset (mode/build family) rather than the match.  When the
    hash changes, the rule set changed and cross-match comparisons need a note.
    """
    canonical = ";".join(f"{key}:{pairs[key]}" for key in sorted(pairs))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def known_fields(located: dict, pairs: dict[int, int]) -> dict:
    """The three scalar words with documented meaning, plus the mode word."""
    words = located["words"]
    return {
        "modeWord": words[1],
        "initialGold": words[2],
        "serverTimeUnixSeconds": words[67],
        "kvMode": pairs.get(1),
        "kvRulesetSha256": kv_ruleset_sha(pairs),
        "kvKeys": len(pairs),
        "scalarBlockSha256": located["scalarSha"],
        "anchorScore": f"{located['score']}/{located['anchorTotal']}",
        "terminator": located["terminator"],
    }
