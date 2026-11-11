"""Export one player's decoded instruction layer from a .abc replay.

Reads the frame-command stream through ``tools/full_abc_event_catalog`` (the
decoder that is checked byte-for-byte against the tail 0x02 mirror), keeps the
rows for one unit, and writes:

  * a CSV with every decoded instruction for that player,
  * a Markdown report a coach can read.

What this does *not* do: it never derives a position from a direction.  The
replay records input direction, not world position, and integrating direction
into a trajectory was refuted (docs 5.132).  Missing channels are reported as
missing, with the reason.

Usage:
    python scripts/replay_instruction_report.py \
        --abc data/replays/samples/20261102_161129/<file>.abc \
        --unit 12 --out-prefix datasets/replay_instructions_20261102_161129
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

import replay_time  # noqa: E402
from tools.full_abc_event_catalog import build_report  # noqa: E402
from tools.replay_input_timeline import load_prices  # noqa: E402

SECTORS = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']
FAMILY_LABEL = {
    'movement': '移动', 'attack': '普攻', 'skill': '技能',
    'buy': '购买', 'cc': '状态', 'aim': '落点', 'ai_state': 'AI',
}
#: Channels this build does not write at all (see docs/evidence_audit.md §1.3).
ABSENT_CHANNELS = {
    '0x2d 朝向': '本文件的包装 TLV 里没有 angle 通道（十人全为空）；'
                 '仓库里唯一的 0x2d 样本是 20260925_105224（5069040 构建）',
    '0x82 位置锚点': '本局只有张良 70 条、吕布 8 条，其他八人没有',
    'USEPOSITIONSKILL 落点': '本局 78 条全部属于张良与吕布；本选手的瞄准技能只记方向',
}


def equip_names() -> dict[int, tuple[str, str]]:
    """item_id -> (name, attribute note) from whichever price table exists."""
    for path in (ROOT / 'resources' / 'equip_prices.csv',
                 ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
                 / 'agent_equip_prices.csv'):
        if not path.exists():
            continue
        table = {}
        with path.open(encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                if row.get('section') not in (None, 'battle_item'):
                    continue
                try:
                    item = int(row['item_id'])
                except (KeyError, TypeError, ValueError):
                    continue
                table[item] = (row.get('item_name') or '', row.get('note') or '')
        if table:
            return table
    return {}


def compass_of(degree: float) -> str:
    return SECTORS[int(((degree % 360) + 22.5) // 45) % 8]


def circular_mean(degrees: list[float]) -> float:
    """Mean of angles: arithmetic averaging of degrees is meaningless."""
    sine = sum(math.sin(math.radians(d)) for d in degrees)
    cosine = sum(math.cos(math.radians(d)) for d in degrees)
    return round(math.degrees(math.atan2(sine, cosine)) % 360, 1)


def display_name(raw: str) -> str:
    """Drop the zero-width / variation-selector code points the game appends."""
    return ''.join(ch for ch in (raw or '')
                   if ch.isprintable() and ch not in '\ufe0e\ufe0f\u200b\u200c\u200d')


def load_rows(abc: Path, unit: int) -> tuple[list[dict], dict]:
    work = Path(tempfile.mkdtemp(prefix='instruction_'))
    try:
        catalog = dict(build_report(abc, work) or {})
        # The catalog does not return the frame total; its per-family table has
        # the last frame of every family, and the max is the stream end.
        counts = work / 'per_family_counts.csv'
        if counts.exists():
            last = 0
            with counts.open(encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    try:
                        last = max(last, int(row.get('last_frame') or 0))
                    except (TypeError, ValueError):
                        continue
            catalog.setdefault('frames', last)
        rows = []
        with (work / 'events.csv').open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                if row.get('unit') == str(unit):
                    row['fields'] = json.loads(row.get('fields_json') or '{}')
                    rows.append(row)
        return rows, catalog
    finally:
        shutil.rmtree(work, ignore_errors=True)


def describe(row: dict, names: dict) -> str:
    cmd, f = row['command'], row['fields']
    if cmd == 'BUYEQUIP':
        name, note = names.get(int(f.get('equip_id') or 0), ('', ''))
        return f"买 {name or f.get('equip_id')}（参考价 {f.get('price')}）{note}"
    if cmd == 'LEARNSKILL':
        return f"加点 slot{f.get('slot')} 第{int(f.get('level', 0)) + 1}点"
    if cmd == 'USEDIRECTIONALSKILL':
        return (f"slot{f.get('slot')} 方向 {f.get('degree_deg')}°"
                f"（罗盘 {compass_of(f.get('degree_deg') or 0)}）"
                f" 第{f.get('skill_seq')}次")
    if cmd == 'USEOBJECTIVESKILL':
        return f"slot{f.get('slot')} 目标对象 {f.get('object_id')} 第{f.get('skill_seq')}次"
    if cmd == 'USEPOSITIONSKILL':
        return f"slot{f.get('slot')} 落点 ({f.get('target_x')}, {f.get('target_y')})"
    if cmd == 'PLAYER_MOVE':
        return f"移动 {f.get('dir_deg')}°（罗盘 {f.get('compass_deg')}）"
    if cmd in ('PLAYER_ATTACK', 'PLAYER_ATTACKWITHOBJ'):
        target = f.get('target_object_id') or f.get('object_id')
        return f"普攻 seq{f.get('seq')}" + (f" 目标 {target}" if target else '')
    if cmd == 'CC':
        return f"状态 {f.get('key')}={f.get('value')}"
    return cmd


def write_csv(rows: list[dict], names: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['frame', 'time_mmss', 'time_s', 'family', 'command',
                         'detail', 'fields_json'])
        for row in rows:
            writer.writerow([row['frame'], row['time_mmss'], row['time_s'],
                             row['family'], row['command'],
                             describe(row, names), row['fields_json']])


def movement_stats(rows: list[dict]) -> list[tuple[int, int, str, float]]:
    """(bucket_min, moves, top sectors, circular mean) per 5 minutes."""
    buckets: dict[int, list[float]] = collections.defaultdict(list)
    for row in rows:
        if row['command'] == 'PLAYER_MOVE':
            buckets[int(float(row['time_s']) // 300)].append(
                float(row['fields'].get('compass_deg') or 0))
    out = []
    for bucket in sorted(buckets):
        values = buckets[bucket]
        sectors = collections.Counter(compass_of(v) for v in values)
        top = ' / '.join(f'{sector} {hits / len(values) * 100:.0f}%'
                         for sector, hits in sectors.most_common(2))
        out.append((bucket * 5, len(values), top, circular_mean(values)))
    return out


def write_report(rows: list[dict], names: dict, path: Path, meta: dict) -> None:
    buys = [r for r in rows if r['command'] == 'BUYEQUIP']
    learns = [r for r in rows if r['command'] == 'LEARNSKILL']
    directional = [r for r in rows if r['command'] == 'USEDIRECTIONALSKILL']
    objective = [r for r in rows if r['command'] == 'USEOBJECTIVESKILL']
    moves = [r for r in rows if r['command'] == 'PLAYER_MOVE']
    attacks = [r for r in rows if r['family'] == 'attack']
    counts = collections.Counter(r['command'] for r in rows)

    lines: list[str] = []
    add = lines.append
    add(f"# {meta['match']} · {display_name(meta['player'])}（{meta['hero']}）指令层解码")
    add('')
    add(f"- 来源：`{meta['abc_name']}` 的帧命令流（ID1075），逐条解码，"
        f"{meta['unknown_rows']} 条未解")
    add(f"- 选手：{display_name(meta['player'])}（{meta['camp']}方 "
        f"{int(meta['slot']) + 1} 号位，unit {meta['unit']}，entity {meta['entity']}）")
    add(f"- 时间基准：docs 5.129，{replay_time.FPS:g} 帧/秒，"
        f"t = (frame − 1) / {replay_time.FPS:g}，±1s")
    add(f"- 本局帧数：{meta['frames']:,}；本选手解出 {len(rows):,} 条")
    add('')
    add('| 通道 | 条数 | 说明 |')
    add('|---|---:|---|')
    for command, count in counts.most_common():
        add(f"| `{command}` | {count:,} | {FAMILY_LABEL.get(_family(rows, command), '')} |")
    add('')

    add('## 1. 购买')
    add('')
    add(f'共 {len(buys)} 条。价格是装备表参考价，**不是实付金额**；'
        '`BUYEQUIP` 是装备变化通知，价格求和不能当支出（docs 5.130）。')
    add('')
    add('| 时间 | 帧 | 装备 | 参考价 | 自动 | 目标对象 |')
    add('|---|---:|---|---:|---|---:|')
    for row in buys:
        f = row['fields']
        name, _ = names.get(int(f.get('equip_id') or 0), ('', ''))
        add(f"| {row['time_mmss']} | {row['frame']} | {name or f.get('equip_id')} "
            f"({f.get('equip_id')}) | {f.get('price')} | {f.get('auto_buy')} "
            f"| {f.get('object_id')} |")
    add('')

    add('## 2. 技能加点')
    add('')
    add(f'共 {len(learns)} 次。顺序：' +
        ' → '.join(f"slot{r['fields'].get('slot')}" for r in learns))
    add('')
    add('| 时间 | 帧 | 技能槽 | 第几点 |')
    add('|---|---:|---|---:|')
    for row in learns:
        f = row['fields']
        add(f"| {row['time_mmss']} | {row['frame']} | slot{f.get('slot')} "
            f"| {int(f.get('level', 0)) + 1} |")
    add('')

    add('## 3. 技能释放')
    add('')
    by_slot = collections.Counter(r['fields'].get('slot') for r in directional)
    add(f'- 方向技能 `USEDIRECTIONALSKILL`：{len(directional)} 条，'
        f'槽位分布 {dict(by_slot)}')
    obj_slots = collections.Counter(r['fields'].get('slot') for r in objective)
    add(f'- 目标技能 `USEOBJECTIVESKILL`：{len(objective)} 条，'
        f'槽位分布 {dict(obj_slots)}')
    add('')
    add('> 槽位号是命令里的原值，仓库里没有「槽位 → 技能名」的验证表。'
        '按施法形态看：slot2 全部带方向（39 次）、slot3 带方向（16 次）、'
        'slot1 全部带目标对象（14 次），与百里守约 2/3/1 技能的形态一致；'
        'slot5（7 次）、slot6（2 次）形态与前三者不同，未定名。')
    add('')
    add('| 时间 | 帧 | 技能 | 方向 | 罗盘 | 目标 | 第几次 |')
    add('|---|---:|---|---:|---|---:|---:|')
    for row in sorted(directional + objective, key=lambda r: int(r['frame'])):
        f = row['fields']
        if row['command'] == 'USEDIRECTIONALSKILL':
            add(f"| {row['time_mmss']} | {row['frame']} | slot{f.get('slot')} "
                f"| {f.get('degree_deg')}° | {compass_of(f.get('degree_deg') or 0)} "
                f"| — | {f.get('skill_seq')} |")
        else:
            add(f"| {row['time_mmss']} | {row['frame']} | slot{f.get('slot')} "
                f"| — | — | {f.get('object_id')} | {f.get('skill_seq')} |")
    add('')

    add('## 4. 移动方向')
    add('')
    add(f'共 {len(moves)} 条输入。**方向不是位置**：方向积分成轨迹已证伪'
        '（锚点残差 1.8 万–6.5 万，docs 5.132）。')
    add('')
    add('| 时段 | 条数 | 主要方向 | 平均罗盘（圆均值） |')
    add('|---|---:|---|---:|')
    for start, count, top, mean in movement_stats(rows):
        add(f'| {start:02d}–{start + 5:02d} 分 | {count:,} | {top} | {mean}° |')
    add('')
    add('> 平均罗盘用圆均值；方向是输入方向，不是位移，也不是位置。')
    add('')

    add('## 5. 普攻')
    add('')
    per_minute = collections.Counter(int(float(r['time_s']) // 60) for r in attacks)
    add(f'共 {len(attacks)} 条（含带目标 {counts.get("PLAYER_ATTACKWITHOBJ", 0)} 条）。')
    add('')
    add('| 分钟 | ' + ' | '.join(str(m) for m in range(max(per_minute) + 1)) + ' |')
    add('|---|' + '---:|' * (max(per_minute) + 1))
    add('| 次数 | ' + ' | '.join(str(per_minute.get(m, 0))
                                for m in range(max(per_minute) + 1)) + ' |')
    add('')

    add('## 6. 本局拿不到的通道')
    add('')
    add('| 通道 | 原因 |')
    add('|---|---|')
    for channel, reason in ABSENT_CHANNELS.items():
        add(f'| {channel} | {reason} |')
    add('')
    add('> 这一节不是"没解出来"，是文件里没有写。要补只能走营地接口、录屏 OCR '
        '或结算截图，见 `docs/replay_sources_matrix.md`。')
    add('')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _family(rows: list[dict], command: str) -> str:
    for row in rows:
        if row['command'] == command:
            return row['family']
    return ''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--abc', type=Path, required=True)
    parser.add_argument('--unit', type=int, required=True)
    parser.add_argument('--out-prefix', type=Path, required=True,
                        help='输出前缀，生成 <prefix>.csv 与 <prefix>.md')
    args = parser.parse_args()

    rows, catalog = load_rows(args.abc, args.unit)
    if not rows:
        print(f'unit {args.unit} 没有解出任何指令', file=sys.stderr)
        return 2
    names = equip_names()
    first = rows[0]
    match = '_'.join(args.abc.stem.split('_')[:2])
    meta = {
        'match': match, 'player': first['player'], 'hero': first['hero'],
        'camp': '蓝' if first['camp'] == '1' else '红', 'slot': first['slot'],
        'unit': args.unit, 'entity': first['entity_id'],
        'abc_name': args.abc.name,
        'frames': catalog.get('frames') or catalog.get('frame_records') or 0,
        'unknown_rows': catalog.get('unknown_rows', 0),
    }
    if not meta['frames']:
        meta['frames'] = max(int(r['frame']) for r in rows)
        print(f'[warn] catalog 没给帧数，用本选手末帧 {meta["frames"]} 顶替',
              file=sys.stderr)

    csv_path = args.out_prefix.with_suffix('.csv')
    md_path = args.out_prefix.with_suffix('.md')
    write_csv(rows, names, csv_path)
    write_report(rows, names, md_path, meta)
    print(f'{meta["player"]}（{meta["hero"]}）unit {args.unit}: {len(rows):,} 条指令')
    print(f'OUT {csv_path}')
    print(f'OUT {md_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
