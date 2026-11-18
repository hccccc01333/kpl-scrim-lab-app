"""回填 KPL 2024-10 之后的逐手 `draftEvents`。

背景：`data/kpl/bp_games.jsonl` 里 2024 年度总决赛起的 5 Ban 局只有每方名单、
没有逐手事件（3,526 局），导致 KPL 2025+ 的手序分析只能覆盖少数局。

做法：按 `battleId` 重新抓官方单局快照，解析 `bp_list`，只把 `draftEvents`
与 `bpMode/bansKnown/pickOrderKnown/fetchedAt` 写回原行；`picks/bans/比分/选手`
等既有字段一律保留。写前整文件备份，临时文件原子替换。

用法：
    python scripts/backfill_kpl_draft_events.py --limit 10   # 先试 10 局
    python scripts/backfill_kpl_draft_events.py             # 全量
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import kpl_bp  # noqa: E402


def rows_needing_backfill(rows):
    result = []
    for row in rows:
        if row.get("draftEvents"):
            continue
        bans = row.get("bans") or {}
        if len(bans.get("1") or []) != 5 or len(bans.get("2") or []) != 5:
            continue
        if row.get("bpMode") not in ("full", None):
            continue
        result.append(row)
    return result


def load_rows(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_rows(path, rows):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Backfill KPL draftEvents")
    parser.add_argument("--path", default=str(kpl_bp.GAMES_PATH))
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 局；0 = 全部")
    parser.add_argument("--sleep", type=float, default=0.12, help="每局之间的间隔秒数")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.path)
    rows = load_rows(path)
    targets = rows_needing_backfill(rows)
    if args.limit:
        targets = targets[:args.limit]
    print(f"rows={len(rows)} targets={len(targets)} dry_run={args.dry_run}", flush=True)
    if not targets or args.dry_run:
        return

    backup = path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_bytes(path.read_bytes())
    print(f"backup={backup.name}", flush=True)

    session = kpl_bp.make_session()
    updated, failed = 0, []
    started = time.time()
    for index, row in enumerate(targets, 1):
        battle_id = str(row.get("battleId") or "")
        try:
            payload = kpl_bp.fetch_battle(session, battle_id)
            if not payload:
                raise ValueError("empty response")
            parsed = kpl_bp.parse_battle(
                payload, battle_id=battle_id,
                game_seq=row.get("gameSeq") or 0)
            events = parsed.get("draftEvents") or []
            if len(events) not in (18, 20):
                raise ValueError(f"events={len(events)}")
            row["draftEvents"] = events
            row["bpMode"] = parsed.get("bpMode") or row.get("bpMode")
            row["bansKnown"] = bool(parsed.get("bansKnown"))
            row["pickOrderKnown"] = bool(parsed.get("pickOrderKnown"))
            row["fetchedAt"] = parsed.get("fetchedAt") or kpl_bp.now_iso()
            updated += 1
        except Exception as error:  # noqa: BLE001 - 单局失败不阻断整轮回填
            failed.append((battle_id, str(error)[:160]))
        if index % 50 == 0 or index == len(targets):
            rate = index / max(0.001, time.time() - started)
            print(f"{index}/{len(targets)} updated={updated} failed={len(failed)} "
                  f"{rate:.1f}/s", flush=True)
        time.sleep(max(0.0, args.sleep))

    write_rows(path, rows)
    print(f"done updated={updated} failed={len(failed)} -> {path}", flush=True)
    for battle_id, reason in failed[:20]:
        print(f"  FAIL {battle_id}: {reason}", flush=True)


if __name__ == "__main__":
    main()
