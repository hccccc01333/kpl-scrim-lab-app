"""Map 0x1e victim IDs against hero object IDs and unit ranges (read-only)."""
from __future__ import annotations
import csv, gzip, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / 'data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz'
OUT = ROOT / 'data/replays/_analysis/datasets'

def main():
    interactions = []
    hero_map = defaultdict(dict)
    with gzip.open(EVENTS, 'rt', encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            fn = r.get('file', '')
            if r.get('kind') == 'unit_interaction':
                interactions.append(r)
            elif r.get('kind') in ('learn_skill', 'buy_equip'):
                entity = r.get('hero_id') or r.get('actor_id')
                ex = r.get('extra') or {}
                hid = ex.get('hero_object_id') if ex.get('hero_object_id') is not None else ex.get('object_id')
                if entity is not None and hid is not None:
                    hero_map[fn][entity] = hid

    rows, summary = [], []
    for fn in sorted({r['file'] for r in interactions}):
        rs = [r for r in interactions if r['file'] == fn]
        hero_ids = set(hero_map.get(fn, {}).values())
        matched = [r for r in rs if r.get('target_id') in hero_ids]
        by_victim = Counter(r.get('target_id') for r in rs)
        shared = Counter()
        attackers = defaultdict(set)
        for r in rs:
            attackers[r.get('target_id')].add(r.get('hero_id'))
        shared = {v: len(a) for v, a in attackers.items() if len(a) > 1}
        for r in rs:
            rows.append(dict(file=fn, frame=r.get('frame_index'), seq=r.get('seq'),
                             attacker_entity=r.get('hero_id'),
                             attacker_player=(r.get('extra') or {}).get('player', ''),
                             victim=r.get('target_id'),
                             interaction_type=(r.get('extra') or {}).get('type', ''),
                             is_hero_object=1 if r.get('target_id') in hero_ids else 0,
                             shared_by_n_attackers=shared.get(r.get('target_id'), 1),
                             raw_hex=r.get('raw_hex', '')))
        summary.append(dict(file=fn, events=len(rs), hero_object_matches=len(matched),
                            distinct_victims=len(by_victim),
                            top_victims=' '.join(f'{v}:{n}' for v, n in by_victim.most_common(10)),
                            shared_victims=' '.join(f'{v}:{n}' for v, n in sorted(shared.items(), key=lambda x: -x[1])[:10])))

    with open(OUT / 'victim_id_events.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(OUT / 'victim_id_summary.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
    print('events', len(rows), 'files', len(summary), 'hero-object matches', sum(r['hero_object_matches'] for r in summary))
    for r in summary:
        print(r)

if __name__ == '__main__':
    main()
