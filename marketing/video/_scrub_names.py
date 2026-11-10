#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把演示库里混进来的真实营地昵称换成合成昵称（只动 marketing/video/.demo）。

营地原始昵称里夹着 U+2061/U+2062 这类不可见字符，字符串精确匹配会漏，
所以按字段名统一改写，而不是按值替换。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent / ".demo"
DB = BASE / "training.sqlite3"
CN = "一二三四五六七八九十"

mapping: dict[str, str] = {}
_counter = [0]


def fake(old: str) -> str:
    if old in mapping:
        return mapping[old]
    n = _counter[0] % 10
    _counter[0] += 1
    label = f"示例选手·{CN[n]}"
    mapping[old] = label
    return label


def scrub(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if ("nick" in k.lower() or k == "ownerName") and isinstance(v, str) and v.strip():
                o[k] = fake(v)
            else:
                scrub(v)
    elif isinstance(o, list):
        for v in o:
            scrub(v)


def main() -> int:
    if not DB.is_file():
        print("missing", DB)
        return 1
    con = sqlite3.connect(DB)
    rows = con.execute("select id, body from channels").fetchall()
    changed = 0
    for cid, body_text in rows:
        try:
            body = json.loads(body_text)
        except ValueError:
            continue
        before = json.dumps(body, ensure_ascii=False, sort_keys=True)
        mapping.clear()
        _counter[0] = 0
        scrub(body)
        if json.dumps(body, ensure_ascii=False, sort_keys=True) != before:
            con.execute("update channels set body = ? where id = ?",
                        (json.dumps(body, ensure_ascii=False), cid))
            changed += 1
    con.commit()
    con.close()

    files = 0
    for path in BASE.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        mapping.clear()
        _counter[0] = 0
        scrub(data)
        if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            files += 1
    print(f"channels={changed} json={files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
