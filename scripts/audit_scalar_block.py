"""Audit the 443-byte ``.abc`` init scalar block across every local sample.

The block lives between the ``svr2GamecoreCfg`` KV array and the first player
block; :mod:`abc_init_block` owns the location logic.  Only three words have a
documented meaning (1 modeWord, 2 initialGold, 67 server time).  This tool
invents no names: it classifies every word and byte as constant / few-variant /
per-match, checks which words track a known match attribute, and looks for a
databin table that reproduces the constants.

    python scripts/audit_scalar_block.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abc_init_block import (  # noqa: E402
    ANCHOR_WORDS, KNOWN_WORDS, SCALAR_BYTES, SCALAR_COUNT,
    kv_pairs, kv_ruleset_sha, locate, server_stamp_from_name)

SAMPLES = ROOT / "data/replays/samples"
TABLES_CSV = ROOT / "data/replays/_analysis/device/tables_blocks.csv"
BLOCKS = ROOT / "data/replays/_analysis/device/dtab_blocks"


def collect() -> list[dict]:
    from replay_parser import parse_header

    rows: list[dict] = []
    for path in sorted(SAMPLES.rglob("*.abc")):
        data = path.read_bytes()
        located = locate(data)
        if located is None:
            rows.append({"file": str(path.relative_to(SAMPLES)),
                         "supported": False, "bytes": len(data)})
            continue
        try:
            header = parse_header(data)
        except Exception:  # noqa: BLE001 - a bad header must not stop the sweep
            header = {}
        pairs = kv_pairs(data, located)
        file_time = server_stamp_from_name(path.stem)
        rows.append({
            "file": str(path.relative_to(SAMPLES)),
            "supported": True,
            "bytes": len(data),
            "builds": header.get("builds"),
            "versions": header.get("versions"),
            "anchorScore": located["score"],
            "anchorTotal": located["anchorTotal"],
            "terminator": located["terminator"],
            "kvCount": located["kvCount"],
            "kvMode": pairs.get(1),
            "kvRulesetSha": kv_ruleset_sha(pairs),
            "mapType": header.get("mapType"),
            "mapId": header.get("mapId"),
            "totalFrames": header.get("totalFrameNum"),
            "scalarStart": located["scalarStart"],
            "scalarSha": located["scalarSha"],
            "fileTime": file_time,
            "block": located["block"],
            "words": located["words"],
        })
    return rows


def classify_words(rows: list[dict]) -> list[dict]:
    good = [row for row in rows if row["supported"]]
    out = []
    for index in range(SCALAR_COUNT):
        values = [row["words"][index] for row in good]
        distinct = sorted(set(values))
        entry = {
            "index": index,
            "distinct": len(distinct),
            "values": distinct[:10],
            "known": KNOWN_WORDS.get(index),
        }
        if len(distinct) == 1:
            entry["class"] = "constant"
        elif len(distinct) <= 8:
            entry["class"] = "few-variants"
        else:
            entry["class"] = "per-match"
        times = [row["fileTime"] for row in good]
        if times and all(t is not None for t in times) and values == times:
            entry["class"] = "server-time"
            entry["known"] = "serverTimeUnixSeconds"
        out.append(entry)
    return out


def classify_bytes(rows: list[dict]) -> dict:
    good = [row for row in rows if row["supported"]]
    if not good:
        return {"constantNonZero": 0, "zero": 0, "varying": []}
    blocks = [row["block"] for row in good]
    varying = []
    constant_nonzero = 0
    zero = 0
    for offset in range(SCALAR_BYTES):
        values = sorted({block[offset] for block in blocks})
        if len(values) == 1:
            if values[0] == 0:
                zero += 1
            else:
                constant_nonzero += 1
        else:
            varying.append({"offset": offset, "word": offset // 4,
                            "byteInWord": offset % 4, "values": values[:12]})
    return {"constantNonZero": constant_nonzero, "zero": zero,
            "varying": varying}


def correlates(rows: list[dict], key: str) -> bool:
    """True when an attribute explains the word across the whole sample set.

    The attribute must repeat (two or more distinct values, each seen twice or
    more) and must cover most samples.  A per-match attribute such as the frame
    count repeats only through duplicate files, so it would otherwise correlate
    with everything; requiring coverage rejects that.
    """
    groups: dict = collections.defaultdict(list)
    for row in rows:
        attr = row.get(key)
        if attr is None:
            return False
        groups[attr].append(row["value"])
    repeated = {attr: values for attr, values in groups.items() if len(values) >= 2}
    if len(repeated) < 2:
        return False
    covered = sum(len(values) for values in repeated.values())
    if covered < 0.8 * len(rows):
        return False
    return all(len(set(values)) == 1 for values in repeated.values())


def attribute_correlation(rows: list[dict], indices: list[int]) -> list[dict]:
    out = []
    for index in indices:
        view = [{"value": row["words"][index],
                 "kvMode": row["kvMode"],
                 "mapId": row["mapId"],
                 "totalFrames": row["totalFrames"],
                 "file": row["file"]} for row in rows]
        hits = [key for key in ("kvMode", "mapId", "totalFrames")
                if correlates(view, key)]
        out.append({"index": index, "correlatesWith": hits, "rows": view})
    return out


def databin_match(values: list[int]) -> list[dict]:
    """Look for a databin table whose 4-byte rows reproduce these words."""
    if not TABLES_CSV.exists():
        return []
    wanted = [value for value in values if value]
    if not wanted:
        return []
    hits = []
    with TABLES_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                stride = int(row["stride"])
                count = int(row["rows"])
                index = int(row["index"])
            except (TypeError, ValueError):
                continue
            if stride != 4 or count < 8:
                continue
            name = Path(row["path"]).name.replace(".bytes", "")
            block = BLOCKS / f"{index}_{name}.bytes.bin"
            if not block.exists():
                continue
            blob = block.read_bytes()
            body = blob[0x98:]
            table = [int.from_bytes(body[i * 4:i * 4 + 4], "little")
                     for i in range(min(count, len(body) // 4))]
            matched = sum(1 for value in wanted if value in table)
            if matched >= 8:
                hits.append({"table": row["path"], "index": index,
                             "rows": count, "matched": matched,
                             "wanted": len(wanted)})
    return sorted(hits, key=lambda item: -item["matched"])[:10]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    rows = collect()
    good = [row for row in rows if row["supported"]]
    words = classify_words(rows)
    bytes_info = classify_bytes(rows)
    counts = collections.Counter(entry["class"] for entry in words)
    varying = [entry["index"] for entry in words if entry["class"] != "constant"]

    print(f"samples: {len(rows)} total, {len(good)} supported, "
          f"{len(rows) - len(good)} unsupported layout")
    if good:
        print(f"kv counts {sorted({row['kvCount'] for row in good})}, "
              f"kv modes {sorted({row['kvMode'] for row in good})}")
        print(f"scalar starts {sorted({row['scalarStart'] for row in good})}, "
              f"terminators {sorted({row['terminator'] for row in good})}")
        print(f"anchor scores {sorted({row['anchorScore'] for row in good})}"
              f" / {good[0]['anchorTotal']}")
        print(f"mapIds {sorted({row['mapId'] for row in good}, key=str)}")
        print(f"distinct scalar blocks: {len({row['scalarSha'] for row in good})}")
        print(f"distinct KV rulesets: {len({row['kvRulesetSha'] for row in good})}")
        print()
        print("per sample:")
        for row in good:
            print(f"  {row['file'][:44]:44s} start={row['scalarStart']:4d} "
                  f"term={row['terminator']:7s} map={row['mapId']} "
                  f"frames={row['totalFrames']}")
        skipped = [row for row in rows if not row["supported"]]
        if skipped:
            print(f"\nunsupported ({len(skipped)}): no 1..10 confType head")
            for row in skipped:
                print(f"  {row['file']}")
    print()
    print(f"word classes: {dict(counts)}")
    print(f"bytes: {bytes_info['constantNonZero']} nonzero constant, "
          f"{bytes_info['zero']} zero constant, {len(bytes_info['varying'])} varying")
    print()
    print("varying words:")
    for entry in words:
        if entry["class"] == "constant":
            continue
        print(f"  [{entry['index']:3d}] {entry['class']:13s} "
              f"distinct={entry['distinct']:2d} values={entry['values']}"
              + (f"  <- {entry['known']}" if entry["known"] else ""))
    print()
    print(f"varying bytes ({len(bytes_info['varying'])}):")
    for entry in bytes_info["varying"]:
        print(f"  offset {entry['offset']:3d} (word {entry['word']:3d}"
              f".+{entry['byteInWord']}): {entry['values']}")
    print()

    if varying:
        print("attribute correlation (repeated attribute -> single value):")
        for entry in attribute_correlation(good, varying):
            print(f"  [{entry['index']:3d}] {entry['correlatesWith'] or 'none'}")
        print()

    if good:
        matches = databin_match(good[0]["words"])
        print("databin tables sharing >=8 nonzero words:")
        if matches:
            for hit in matches:
                print(f"  {hit['matched']:3d}/{hit['wanted']:3d} rows={hit['rows']:5d} "
                      f"idx={hit['index']:3d} {hit['table']}")
        else:
            print("  none")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "schema": "kpl-abc-scalar-audit-v1",
            "anchors": {str(key): value for key, value in ANCHOR_WORDS.items()},
            "samples": [{key: value for key, value in row.items() if key != "block"}
                        for row in rows],
            "wordClasses": words,
            "byteClasses": bytes_info,
            "attributeCorrelation": attribute_correlation(good, varying),
            "databinMatches": databin_match(good[0]["words"]) if good else [],
        }, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
