"""Audit .ope containers and operator streams (read-only).

For every .ope:
  * parse the outer DEFLATE and locate the inner raw-DEFLATE payload
    (0x8B in older resource versions, 0x91 in newer ones);
  * run the observed record-layout parser and report the wall / record counts;
  * mark the known quick-match sample 20261028_135516 (孙膑 / 茉莉花与雨).

The inner payload is raw DEFLATE in the samples here; Oodle is not required.
Record boundaries are inferred; field names beyond frame/unityFrame/eventId
are not ground truth.

Usage:
  python tools/ope_status.py
  python tools/ope_status.py --all
Output:
  data/replays/_analysis/datasets/ope_status.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "data" / "replays" / "_analysis"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(AN / "tools"))
sys.path.insert(0, str(ROOT))

from ope_container import probe  # noqa: E402
from ope_parse import find_payload, parse_stream, semantic_issues, unwrap  # noqa: E402

QUICK_MATCH = {"20261028_135516"}  # 孙膑 / 茉莉花与雨; 5.87/5.101
KEY_NORMAL = {"20260925_105224_-1505729760_4933_1790303631",
              "20261101_182452_-1723849936_94263_1793527939_CBDD358E761B15A4DF526A179E8119E2"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="parse every .ope (slow); default: new/key samples")
    args = parser.parse_args()

    out_rows = []
    for ope in sorted((ROOT / "data" / "replays" / "samples").rglob("*.ope")):
        try:
            info = probe(ope)
        except Exception as exc:  # noqa: BLE001
            out_rows.append({"file": str(ope.relative_to(ROOT)), "error": repr(exc)})
            continue
        quick = 1 if ope.stem in QUICK_MATCH else 0
        row = {
            "file": str(ope.relative_to(ROOT)),
            "clientVersion": info.get("clientVersion") or "",
            "resVersion": info.get("resVersion") or "",
            "build": info.get("build") or "",
            "device": info.get("device") or "",
            "localTime": info.get("localTime") or "",
            "quick_match": quick,
            "payloadOffset": "",
            "streamSize": "",
            "reachableMax": "",
            "wallType": "",
            "parsed": "",
            "semanticOk": "",
            "semanticIssues": "",
            "records": "",
            "tentative": "",
            "ambiguities": "",
        }
        do_parse = args.all or quick or ope.stem in KEY_NORMAL
        if do_parse:
            try:
                inner = unwrap(ope.read_bytes())
                found = find_payload(inner)
                if found is None:
                    raise ValueError("no raw-DEFLATE payload in 0x80..0xA0")
                off, stream = found
                records, ambiguities, wall = parse_stream(stream)
                issues = semantic_issues(records) if records else []
                row.update({
                    "payloadOffset": off,
                    "streamSize": len(stream),
                    "reachableMax": wall,
                    "wallType": f"0x{stream[wall]:02x}" if wall < len(stream) else "",
                    "parsed": int(records is not None),
                    "semanticOk": int(records is not None and not issues),
                    "semanticIssues": "; ".join(issues[:3]),
                    "records": len(records) if records else 0,
                    "tentative": sum(1 for r in records if r["tentative"]) if records else "",
                    "ambiguities": ambiguities if records else "",
                })
            except Exception as exc:  # noqa: BLE001
                row["error"] = repr(exc)
        out_rows.append(row)

    out = AN / "datasets" / "ope_status.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["file", "clientVersion", "resVersion", "build", "device", "localTime",
              "quick_match", "payloadOffset", "streamSize", "reachableMax",
              "wallType", "parsed", "semanticOk", "semanticIssues", "records",
              "tentative", "ambiguities", "error"]
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in out_rows:
            writer.writerow({key: row.get(key, "") for key in fields})

    total = len(out_rows)
    parsed = sum(1 for row in out_rows if row.get("parsed") == 1)
    semantic = sum(1 for row in out_rows if row.get("semanticOk") == 1)
    quick = sum(1 for row in out_rows if row.get("quick_match") == 1)
    print(f"ope files={total} boundary_parsed={parsed} semantic_ok={semantic} quick_match={quick}")
    print(f"out: {out}")
    for row in out_rows:
        if row.get("parsed") in (0, 1):
            print(f"  {Path(row['file']).name[:46]:<48} "
                  f"payload=0x{row['payloadOffset'] or 0:02x} "
                  f"stream={row['streamSize']} max=0x{row['reachableMax'] or 0:04x} "
                  f"parsed={row['parsed']} semantic={row['semanticOk']} "
                  f"records={row['records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
