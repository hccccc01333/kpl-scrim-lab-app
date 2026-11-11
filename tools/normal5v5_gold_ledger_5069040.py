"""普通 5v5（5069040）六样本金币流水汇总（只读）。

只解析 `0x02 flag=0x85 len=5`：sourceType:u8 + amount:u32LE。
玩家/英雄来自 `normal5v5_player_heroes_5069040.csv`（玩家块 s+0x48）。
不修改回放，不注入，不读 param.json。

输出：
  datasets/normal5v5_gold_ledger_5069040.csv
  datasets/normal5v5_gold_summary_5069040.csv
"""
from collections import defaultdict
from pathlib import Path
import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / 'data' / 'replays' / '_analysis'
sys.path.insert(0, str(ANALYSIS / 'tools'))
import abc_tags_full as A  # noqa: E402

SAMPLES = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
DATASETS = ANALYSIS / 'datasets'
HEROES = DATASETS / 'normal5v5_player_heroes_5069040.csv'


def load_heroes():
    out = defaultdict(dict)
    with HEROES.open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            short = '_'.join(r['sample'].split('_')[:2])
            out[short][int(r['entityID'])] = r
    return out


def sample_id(path):
    return path.name.split('_')[0] + '_' + path.name.split('_')[1]


def gold_events(pl):
    """Yield (hero, source, amount); consumes 0x80 12B command bodies."""
    i, out = 1, []
    while i < len(pl):
        t = pl[i]
        if t == 0x12:
            i += 3
        elif t == 0x13:
            i += 2
        elif t == 0x14:
            i += 4
        elif t == 0x01:
            if i + 5 > len(pl):
                break
            i += 5 + pl[i + 4]
        elif t == 0x02:
            if i + 4 > len(pl):
                break
            hero = int.from_bytes(pl[i + 1:i + 3], 'big')
            flag = pl[i + 3]
            if flag == 0x80:
                i += 16
            else:
                ln = flag & 0x7F
                if i + 4 + ln > len(pl):
                    break
                if flag == 0x85 and ln == 5:
                    out.append((hero, pl[i + 4],
                                int.from_bytes(pl[i + 5:i + 9], 'little')))
                i += 4 + ln
        else:
            break
    return out


def main():
    heroes = load_heroes()
    files = sorted(SAMPLES.glob('2026092[45]_*.abc'))
    events = []
    for path in files:
        sid = sample_id(path)
        d = path.read_bytes()
        recs, _ = A.find_stream(d)
        for rec in recs:
            for entity, src, amount in gold_events(rec['payload']):
                    h = heroes.get(sid, {}).get(entity, {})
                    events.append(dict(
                        sample=sid, file=path.name,
                        player=h.get('player', ''), team=h.get('team', ''),
                        slot=h.get('slot', ''), entityID=entity,
                        heroID=h.get('heroID', ''), heroName=h.get('heroName', ''),
                        seq=rec['seq'], time_s=round(rec['seq'] / 20, 2),
                        game_time_s_est=round(rec['seq'] / 20 + 20.3, 2),
                        source=src, amount=amount,
                    ))

    DATASETS.mkdir(parents=True, exist_ok=True)
    with (DATASETS / 'normal5v5_gold_ledger_5069040.csv').open(
            'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(events[0]))
        w.writeheader()
        w.writerows(events)

    agg = defaultdict(lambda: [0, 0])
    for e in events:
        key = (e['sample'], e['player'], e['team'], e['slot'], e['entityID'],
               e['heroID'], e['heroName'], e['source'])
        agg[key][0] += 1
        agg[key][1] += e['amount']
    with (DATASETS / 'normal5v5_gold_summary_5069040.csv').open(
            'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['sample', 'player', 'team', 'slot', 'entityID', 'heroID',
                    'heroName', 'source', 'events', 'total'])
        for key, (n, total) in sorted(agg.items()):
            w.writerow([*key, n, total])

    by_sample = defaultdict(lambda: [0, 0])
    for e in events:
        by_sample[e['sample']][0] += 1
        by_sample[e['sample']][1] += e['amount']
    print(f'{len(events)} events, {len(files)} samples')
    for sid, (n, total) in sorted(by_sample.items()):
        print(f'  {sid:<22} events={n:<4} gold={total}')


if __name__ == '__main__':
    main()
