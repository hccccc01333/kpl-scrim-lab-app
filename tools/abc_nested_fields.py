#!/usr/bin/env python3
"""Read-only nested-tag extractor for the 5069040 .abc frame stream.

Top-level 0x01 is a container:
    01 | entity:u16BE | flag:u8(=0) | len:u8 | body[len]
The real subtag is body[0]. This tool emits the field-level rows for the
nested 0x2d/0x2c/0x1e/0x29/0x1f/0x20/0x03/0x23/0x87 tags.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import replay_parser as rp

DEFAULT_ABC = (ROOT / "data/replays/samples/abc_batch"
               / "20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc")
DEFAULT_OUT = ROOT / "data/replays/_analysis/datasets/abc_nested_events_5069040.csv"

FIELDS = [
    "frame", "offset", "entity", "subtag",
    "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7",
    "raw_hex",
]


def nested_rows(frame: int, offset: int, entity: int, body: bytes):
    if not body:
        return
    tag = body[0]
    if tag == 0x2D and len(body) == 3:
        yield ["0x2d", int.from_bytes(body[1:3], "big")]
    elif tag == 0x03 and len(body) == 2:
        yield ["0x03", body[1]]
    elif tag == 0x23 and len(body) == 2:
        yield ["0x23", body[1]]
    elif tag == 0x87 and len(body) == 5:
        yield ["0x87", int.from_bytes(body[1:5], "big")]
    elif tag == 0x2C and len(body) == 17:
        kind = body[1]
        flag = body[2]
        target = int.from_bytes(body[3:5], "big")
        x = int.from_bytes(body[5:9], "big", signed=True)
        y = int.from_bytes(body[9:13], "big", signed=True)
        counter = int.from_bytes(body[13:17], "big")
        yield ["0x2c", kind, flag, target, x, y, counter]
    elif tag == 0x1E and len(body) == 19:
        yield ["0x1e", body[1], int.from_bytes(body[16:18], "big"), body[18]]
    elif tag == 0x29 and len(body) == 17:
        yield ["0x29", body[4], int.from_bytes(body[5:9], "big"),
               int.from_bytes(body[9:13], "big", signed=True),
               int.from_bytes(body[13:17], "big")]
    elif tag == 0x1F and len(body) == 28:
        yield ["0x1f", body[1],
               int.from_bytes(body[2:6], "big"),
               int.from_bytes(body[6:10], "big"),
               int.from_bytes(body[10:14], "big", signed=True),
               int.from_bytes(body[14:18], "big"),
               int.from_bytes(body[18:22], "big"),
               int.from_bytes(body[22:24], "big"),
               body[24:28].hex()]
    elif tag == 0x20 and len(body) == 20:
        yield ["0x20", body[1], body[2:6].hex(), body[6:10].hex(),
               body[10:14].hex(), body[14:18].hex(),
               int.from_bytes(body[18:20], "big")]
    elif tag == 0x48 and len(body) == 9:
        yield ["0x48", body[1:].hex()]


def walk(abc: Path):
    data = abc.read_bytes()
    frames = rp.inspect_frame_stream(data)
    if frames.get("status") != "frame-stream":
        raise SystemExit(f"not a frame stream: {frames}")
    for frame, offset, payload in rp._iter_frame_payloads(data, frames):
        index = 1
        size = len(payload)
        while index < size:
            tag = payload[index]
            if tag == 0x12:
                index += 3
                continue
            if tag == 0x13:
                index += 2
                continue
            if tag == 0x14:
                index += 4
                continue
            if tag == 0x01:
                if index + 5 > size:
                    break
                entity = int.from_bytes(payload[index + 1:index + 3], "big")
                length = payload[index + 4]
                if index + 5 + length > size:
                    break
                body = payload[index + 5:index + 5 + length]
                for row in nested_rows(frame, offset, entity, body):
                    yield [frame, offset, entity, row[0], *row[1:],
                           *([""] * (8 - len(row[1:]))), body.hex()]
                index += 5 + length
                continue
            # 0x02 body length is build-specific; stop this payload safely.
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc", type=Path, default=DEFAULT_ABC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    counts: dict[str, int] = {}
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for row in walk(args.abc):
            writer.writerow(row)
            count += 1
            counts[row[3]] = counts.get(row[3], 0) + 1
    print(f"wrote {count} rows to {args.out}")
    for tag, n in sorted(counts.items()):
        print(f"  {tag}: {n}")


if __name__ == "__main__":
    main()
