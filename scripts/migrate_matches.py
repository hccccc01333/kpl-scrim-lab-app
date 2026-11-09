"""把现有对局迁进结构化 records（workspace_store.match_records）。

数据来源（按优先级合并，match_key 去重）：
  1. data/matches/*.json —— kpl-match-data-v1 数据包（营地口径，主来源）
  2. 老 matches 表里的 body JSON（bundle/channel 形态）
  3. 营地面板 data/camp_details/*.json —— 补 BP 与阵容

幂等：重复执行只更新不重复插入；只填空字段，不覆盖人工值
（status/reviewer/notes 等人工字段由 upsert_match 的 COALESCE 规则保护）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspace_store import Workspace  # noqa: E402
import team_clusters  # noqa: E402


def load_bundles(matches_dir: Path):
    for path in sorted(matches_dir.glob('*.json')):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get('schema') == 'kpl-match-data-v1':
            yield path.stem, value


def load_legacy_rows(db_path: Path):
    import sqlite3
    if not db_path.is_file():
        return
    connection = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
    try:
        try:
            rows = connection.execute('SELECT id, body FROM matches').fetchall()
        except sqlite3.Error:
            return
    finally:
        connection.close()
    for row_id, body in rows:
        try:
            value = json.loads(body)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            yield row_id, value


def load_camp_panels(camp_dir: Path):
    panels = {}
    for panel in team_clusters.load_panels(camp_dir):
        panels[panel['seq']] = panel
    return panels


def bundle_to_record(key: str, value: dict, team_names: dict, own_team_id: str):
    match = value.get('match') or {}
    date = (match.get('date') or {}).get('text') if isinstance(match.get('date'), dict) else match.get('date')
    own_camp = match.get('ownCamp')
    winner = match.get('winnerCamp') or match.get('winner')
    scores = match.get('scores') or {}
    players = value.get('players') or []
    enemy_players = [p for p in players if (p.get('camp') or p.get('side')) != own_camp]
    enemy_key = None
    if len(enemy_players) >= 5:
        try:
            enemy_key = team_clusters.signature({
                'enemy_roster': [{'id': str((p.get('key') or ''))} for p in enemy_players],
            })
        except Exception:
            enemy_key = None
    rosters = [{
        'teamId': own_team_id if (p.get('camp') or p.get('side')) == own_camp else (enemy_key or ''),
        'playerId': str(p.get('key') or p.get('nickname') or ''),
        'side': p.get('camp') or p.get('side') or 'blue',
        'slot': p.get('slot') or 0,
        'hero': p.get('hero'),
    } for p in players]
    camp_bp = match.get('campBp') or {}
    return {
        'match_key': key,
        'date': date,
        'session': match.get('session'),
        'mode': match.get('mode'),
        'version': match.get('version'),
        'own_team_id': own_team_id,
        'enemy_team_id': enemy_key,
        'enemy_cluster_id': enemy_key,
        'own_side': own_camp,
        'winner': winner,
        'score': scores or None,
        'duration': match.get('duration'),
        'status': 'confirmed' if value.get('schema') else 'draft',
        'source': 'bundle',
        'rosters': rosters,
        'bp': {
            'bans': camp_bp.get('bans'),
            'picks': camp_bp.get('picks'),
            'first_pick': camp_bp.get('firstPick'),
        } if camp_bp else None,
    }


def legacy_to_record(key: str, body: dict, own_team_id: str):
    return {
        'match_key': f'db-{key}',
        'date': body.get('date'),
        'session': body.get('session'),
        'version': body.get('version'),
        'own_team_id': own_team_id,
        'own_side': body.get('side'),
        'winner': body.get('winner'),
        'score': body.get('scores'),
        'duration': int(round(float(body.get('duration') or 0) * 60)) or None,
        'status': body.get('status') or 'draft',
        'source': 'db',
        'rosters': [],
        'bp': None,
    }


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data' / 'training.sqlite3'
    matches_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'data' / 'matches'
    camp_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'data' / 'camp_details'

    ws = Workspace(db_path).ensure_schema()

    own_team_id = 'team-own'
    if not any(team['id'] == own_team_id for team in ws.list_teams(include_archived=True)):
        ws.upsert_team(own_team_id, name='我方战队', source='migration')

    # 对手战队：按聚类结果建 teams（命名走覆盖层，未命名的用「待命名战队 #N」）
    clusters = team_clusters.list_teams(camp_dir, db_path, '我方战队')
    for team in clusters['teams']:
        ws.upsert_team(team['id'], name=team['displayName'], source='migration')
    team_names = {team['id']: team['name'] for team in ws.list_teams(include_archived=True)}

    written = 0
    for key, value in load_bundles(matches_dir):
        record = bundle_to_record(key, value, team_names, own_team_id)
        match_key = record.pop('match_key')
        rosters = record.pop('rosters')
        bp = record.pop('bp')
        ws.upsert_match(match_key, **record)
        if rosters:
            ws.upsert_rosters(match_key, rosters)
        if bp:
            ws.upsert_bp(match_key, bans=bp.get('bans'), picks=bp.get('picks'),
                         first_pick=bp.get('first_pick'))
        written += 1

    for key, body in load_legacy_rows(db_path):
        record = legacy_to_record(key, body, own_team_id)
        match_key = record.pop('match_key')
        record.pop('rosters')
        record.pop('bp')
        ws.upsert_match(match_key, **record)
        written += 1

    rows = ws.list_matches(limit=1000)
    print(f'迁移完成：写入/更新 {written} 条，结构化记录共 {len(rows)} 条，'
          f'库 {db_path}')
    for row in rows[:5]:
        print(' ', row['match_key'], row['date'], row['own_side'], row['winner'], row['source'])


if __name__ == '__main__':
    main()
