"""Build 2026-11-02 replay action datasets from decoded frame commands.

BUYEQUIP is a purchase, NOT gold.  This script never labels it as income.
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.replay_frame_commands import events
OUT = ROOT / 'data/replays/_analysis/datasets'
FILES = [
    ROOT / 'data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc',
    ROOT / 'data/replays/samples/20261102_163751/20261102_163751_-1996438720_96420_1793607470_2B9FAA08A7AD40D09ABDA364F9C1E804.abc',
]

def price_map():
    rows = list(csv.DictReader(open(OUT / 'agent_equip_prices.csv', encoding='utf-8-sig')))
    out = {}
    for r in rows:
        if r.get('section') != 'battle_item' or not r.get('item_id'):
            continue
        try:
            out[int(r['item_id'])] = (r['item_name'], int(r['buy_price']))
        except ValueError:
            pass
    return out

def main():
    prices = price_map()
    buys, skills, summaries = [], [], []
    for path in FILES:
        data = path.read_bytes()
        report = json.load(open(path.parent / 'replay-report.json', encoding='utf-8'))
        blocks = {int(b['entityId']): b for b in report.get('blocks', []) if b.get('entityId') is not None}
        ev = list(events(data))
        counts = Counter(e['name'] for e in ev)
        # docs 5.127: packed high 5 bits = unit; camp1 slots 0-4 -> 8-12,
        # camp2 slots 0-4 -> 16-20.  Map unit back to roster entity.
        unit_to_entity = {}
        camp_seen = Counter()
        for b in sorted(report.get('blocks', []),
                        key=lambda x: (int(x.get('camp') or 0), int(x.get('order') or 0))):
            camp = int(b.get('camp') or 0)
            if camp not in (1, 2) or b.get('entityId') is None:
                continue
            pos = b.get('position')
            if pos is None:
                pos = camp_seen[camp]
            camp_seen[camp] += 1
            unit_to_entity[(8 if camp == 1 else 16) + int(pos)] = int(b['entityId'])
        move_by_unit = Counter(e['unit'] for e in ev
                               if e['name'] == 'PLAYER_MOVE' and e.get('unit') is not None)
        attack_by_unit = Counter(e['unit'] for e in ev
                                 if e['name'] in ('PLAYER_ATTACK', 'PLAYER_ATTACKWITHOBJ')
                                 and e.get('unit') is not None)
        attackwithobj_by_unit = Counter(e['unit'] for e in ev
                                       if e['name'] == 'PLAYER_ATTACKWITHOBJ'
                                       and e.get('unit') is not None)
        entity_unit = {entity: unit for unit, entity in unit_to_entity.items()}
        buy_rows = [e for e in ev if e['name'] == 'BUYEQUIP']
        skill_rows = [e for e in ev if e['name'] == 'LEARNSKILL']
        # dedupe identical purchase notification (entity,equip,frame)
        seen = set(); dedup = []
        for e in buy_rows:
            f = e.get('fields', {})
            key = (e.get('object_id'), f.get('equip_id'), e.get('frame'))
            if key in seen:
                continue
            seen.add(key); dedup.append(e)
        per = {}
        first_seen = set()
        for e in dedup:
            entity = e.get('object_id'); f = e.get('fields', {})
            equip = f.get('equip_id')
            name, price = prices.get(equip, ('?', 0))
            b = blocks.get(entity, {})
            first = (entity, equip) not in first_seen
            first_seen.add((entity, equip))
            row = dict(file=path.name, frame=e['frame'], entity=entity,
                       player=b.get('name', ''), hero_id=b.get('heroId', ''),
                       equip_id=equip, equip_name=name, buy_price=price,
                       auto_buy=f.get('auto_buy', ''),
                       first_for_entity=1 if first else 0)
            buys.append(row)
            p = per.setdefault(entity, dict(file=path.name, entity=entity,
                                            player=b.get('name', ''), hero_id=b.get('heroId', ''),
                                            buys=0, first=0, spend=0, equip_ids=set()))
            p['buys'] += 1; p['equip_ids'].add(equip)
            if first:
                p['first'] += 1; p['spend'] += price
        for e in skill_rows:
            entity = e.get('object_id'); f = e.get('fields', {})
            b = blocks.get(entity, {})
            skills.append(dict(file=path.name, frame=e['frame'], entity=entity,
                               player=b.get('name', ''), hero_id=b.get('heroId', ''),
                               slot=f.get('slot'), level=f.get('level'), auto_learn=f.get('auto_learn')))
        # score table
        score = {}
        for s in report.get('scoreTable', {}).get('players', []):
            score[int(s['entityId'])] = s.get('score')
        # per-player summary
        for entity, b in blocks.items():
            p = per.get(entity, {})
            p_skills = [s for s in skills if s['entity'] == entity]
            skill_counts = Counter(int(s['slot']) for s in p_skills if s.get('slot') is not None)
            # CS commands with object_id are per-player
            obj_events = [e for e in ev if e.get('object_id') == entity]
            unit = entity_unit.get(entity)
            summaries.append(dict(
                file=path.name, entity=entity, player=b.get('name', ''), hero_id=b.get('heroId', ''),
                unit='' if unit is None else unit,
                score=score.get(entity, ''), buy_events_raw=p.get('buys', 0),
                unique_buy_items=p.get('first', 0),
                unique_equip_price_sum_unverified=p.get('spend', 0),
                buy_equip_ids=' '.join(map(str, sorted(p.get('equip_ids', set())))),
                learn_events=len(p_skills),
                learn_slots=' '.join(f'{k}:{v}' for k, v in sorted(skill_counts.items())),
                move_events=move_by_unit.get(unit, 0),
                attack_events=attack_by_unit.get(unit, 0),
                attackwithobj_events=attackwithobj_by_unit.get(unit, 0),
                move_events_file_total=sum(1 for e in ev if e['name'] == 'PLAYER_MOVE'),
                attack_events_file_total=sum(1 for e in ev if e['name'] == 'PLAYER_ATTACK'),
                attackwithobj_events_file_total=sum(1 for e in ev if e['name'] == 'PLAYER_ATTACKWITHOBJ'),
                per_player_attribution='unit_high5_camp_slot',
                directional_skill=sum(1 for e in obj_events if e['name'] == 'USEDIRECTIONALSKILL'),
                position_skill=sum(1 for e in obj_events if e['name'] == 'USEPOSITIONSKILL'),
                objective_skill=sum(1 for e in obj_events if e['name'] == 'USEOBJECTIVESKILL'),
            ))
        print(path.name, 'events', len(ev), 'buys_raw', len(buy_rows), 'buys_unique', len(dedup), 'skills', len(skill_rows), 'counts', dict(counts))
    def dump(name, rows):
        with open(OUT / name, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    dump('20261102_buy_events.csv', buys)
    dump('20261102_skill_events.csv', skills)
    dump('20261102_player_actions.csv', summaries)
    print('wrote', len(buys), len(skills), len(summaries))

if __name__ == '__main__':
    main()
