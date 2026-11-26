"""4.0 统一采集上下文：视角校验 → playerId 双匹配池 → 批量匹配 → 最后 BO 编组。

设计边界
--------
* 十人面板的解析完全复用 team_clusters.load_panels()（其中已用 head.acntCamp
  判本局视角、用 basicInfo.playerId 取稳定 ID），本模块不重写解析算法。
* 采集账号视角（`head.acntCamp` 推出的 panel['own']）只做校验与提示：
  绝不据此自动改写历史对局的阵营；视角与上下文不一致时给出 warning。
* 昵称是匹配线索，不是身份主键；稳定键始终是 playerId（营地 playerId /
  本地选手 ID）。昵称池按 own/enemy 两侧分开，避免跨阵营撞名。
* 本模块只写新表（capture_batches / player_nickname_pool）和权威对局表的
  归属列；不写 camp_details、不改营地同步产物。
"""
from __future__ import annotations

from pathlib import Path

import team_clusters
from workspace_store import Workspace


def analyze(db_path, camp_dir, *, batch, entries=None, at_date=None):
    """分析一批勾选对局：视角校验 + 账号批量匹配 + 双昵称池行。"""
    ws = Workspace(db_path).ensure_schema()
    panels = team_clusters.load_panels(Path(camp_dir))
    by_seq = {panel['seq']: panel for panel in panels}
    expected_side = str(batch.get('expectedOwnSide') or '').strip() or None
    if expected_side not in (None, 'blue', 'red'):
        raise ValueError('上下文中的本队视角只能是 blue / red')
    rows = []
    warnings = []
    seen_keys = set()
    sources = entries if entries is not None else [
        {'gameSeq': panel['seq']} for panel in panels]
    for entry in sources or []:
        seq = str(entry.get('gameSeq') or '').strip()
        panel = by_seq.get(seq)
        if panel is None:
            warnings.append({'gameSeq': seq, 'level': 'warning',
                             'message': '没有解析到该局的十人面板，跳过'})
            continue
        match_key = f'camp:{seq}'
        if match_key in seen_keys:
            warnings.append({'gameSeq': seq, 'level': 'warning',
                             'message': '同一局被重复勾选，只处理一次'})
            continue
        seen_keys.add(match_key)
        viewpoint = panel['own']  # 由 head.acntCamp 推出，代表采集账号所在方
        if expected_side and viewpoint != expected_side:
            warnings.append({'gameSeq': seq, 'level': 'warning',
                             'message': f'本局视角为 {viewpoint}，与上下文本队视角 {expected_side} 不一致，请核对采集账号'})
        # own/enemy 是采集账号视角；双匹配池按「本队/对手」而非「蓝/红」归档。
        own_side = expected_side or viewpoint
        own_panel_key = 'own' if own_side == viewpoint else 'enemy'
        account_id = str(entry.get('accountId') or '').strip()
        nickname = str(entry.get('ownerName') or entry.get('nickname') or '').strip()
        resolved = ws.resolve_player_at(account_id, at_date=at_date,
                                        game_match_key=match_key) if account_id else None
        source = 'account' if resolved else ''
        if resolved is None and nickname:
            # 昵称只在同侧池里找：蓝红两边同名撞车是本队/对手最常见的误匹配来源。
            pool_player = ws.find_nickname_player(nickname, side=own_panel_key)
            if pool_player:
                resolved = {'playerId': pool_player, 'source': 'nickname'}
                source = 'nickname'
        if resolved is None:
            warnings.append({'gameSeq': seq, 'level': 'warning',
                             'message': f'游戏账号 {account_id or nickname or "?"} 未匹配到本地选手'})
        pool_rows = []
        for side_key in ('own', 'enemy'):
            pool_side = 'own' if side_key == own_panel_key else 'enemy'
            for player in panel[f'{side_key}_roster']:
                pool_rows.append({
                    'side': pool_side,
                    'playerId': player.get('id') or None,
                    'nickname': player.get('name') or '',
                    'matchKey': match_key,
                    'lane': player.get('lane') or None,
                    'confidence': 'high' if player.get('id') else 'low',
                    'seenAt': str(panel.get('start') or '')[:10] or None,
                    'hero': player.get('hero') or '',
                })
        rows.append({
            'gameSeq': seq,
            'matchKey': match_key,
            'viewpoint': viewpoint,
            'ownSide': own_side,
            'accountId': account_id,
            'nickname': nickname,
            'playerId': (resolved or {}).get('playerId') or None,
            'matchSource': source,
            'start': panel.get('start') or '',
            'win': panel.get('win'),
            'rosterCount': len(panel['own_roster']) + len(panel['enemy_roster']),
            'warnings': [],
        })
    return {'rows': rows, 'poolRows': pool_rows_aggregate(rows, panels),
            'warnings': warnings, 'panelCount': len(panels)}


def pool_rows_aggregate(rows, panels=None):
    """按 (side, playerId, nickname) 去重聚合，保留最近一次出现。"""
    by_seq = {panel['seq']: panel for panel in (panels or [])}
    collected = {}
    for row in rows:
        panel = by_seq.get(str(row.get('gameSeq')))
        if panel is None:
            continue
        # panel['own'] 是采集账号所在颜色，row['ownSide'] 是上下文本队颜色；
        # 先把颜色换算成面板的 own/enemy，再归入本队/对手双池。
        own_panel_key = 'own' if (row.get('ownSide') or panel['own']) == panel['own'] else 'enemy'
        for side_key in ('own', 'enemy'):
            pool_side = 'own' if side_key == own_panel_key else 'enemy'
            for player in panel[f'{side_key}_roster']:
                name = player.get('name') or ''
                if not name:
                    continue
                key = (pool_side, player.get('id') or '', name)
                item = collected.get(key)
                if item is None or str(row.get('start') or '') > str(item.get('seenAt') or ''):
                    collected[key] = {
                        'side': pool_side, 'playerId': player.get('id') or None,
                        'nickname': name, 'matchKey': row.get('matchKey'),
                        'lane': player.get('lane') or None,
                        'confidence': 'high' if player.get('id') else 'low',
                        'seenAt': str(row.get('start') or '')[:10] or None,
                    }
    return list(collected.values())


def commit(db_path, batch_id, analysis, *, entries=None):
    """落双昵称池 + 给本批对局盖上当前赛事上下文。"""
    ws = Workspace(db_path).ensure_schema()
    batch = ws.get_capture_batch(batch_id)
    if batch is None:
        raise ValueError('采集批次不存在')
    rows = (analysis or {}).get('rows') or []
    saved = ws.upsert_nickname_entries((analysis or {}).get('poolRows') or [])
    match_keys = [row['matchKey'] for row in rows if row.get('matchKey')]
    stamped = ws.stamp_capture_context(
        match_keys, competition_id=batch.get('competition_id'),
        match_type=batch['match_type'], own_team_id=batch['own_team_id'],
        enemy_team_id=batch['opponent_team_id'], source='camp-context')
    report = {'matchKeys': match_keys, 'poolRows': saved, 'stamped': stamped,
              'warnings': (analysis or {}).get('warnings') or []}
    ws.update_capture_batch(batch_id, status='committed', report=report)
    return report


def group_series(db_path, batch_id, match_keys, *, best_of=3, series_id=None):
    """最后一步 BO 编组：沿用现有 create_series 的冲突检查，不另写一套。"""
    ws = Workspace(db_path).ensure_schema()
    batch = ws.get_capture_batch(batch_id)
    if batch is None:
        raise ValueError('采集批次不存在')
    if len(match_keys or []) > int(best_of):
        raise ValueError(f'BO{best_of} 最多 {best_of} 局')
    series = ws.create_series(
        best_of=best_of, games=list(match_keys or []), series_id=series_id,
        opponent_team_id=batch['opponent_team_id'],
        session=batch.get('notes') or None,
        competition_id=batch.get('competition_id'),
        actor=(batch.get('actor') or 'coach'))
    return series


def stamp_synced_entries(db_path, *, competition_id=None, own_team_id=None,
                         opponent_team_id=None, match_type=None, entries=None):
    """营地同步完成后的轻量回填钩子：只盖归属，不碰营地产物。

    对局包是懒登记进 match_records 的，因此这里对缺行按营地列表自带的 date
    补一条 draft 归属记录；日期缺失时宁可不建，也不猜时间。
    """
    if not competition_id and not own_team_id and not opponent_team_id:
        return 0
    ws = Workspace(db_path).ensure_schema()
    saved = 0
    connection = ws.connect()
    try:
        existing = {row[0] for row in connection.execute('SELECT match_key FROM match_records')}
    finally:
        connection.close()
    for entry in entries or []:
        seq = str(entry.get('gameSeq') or '').strip()
        if not seq:
            continue
        key = f'camp:{seq}'
        own_side = {'1': 'blue', '2': 'red'}.get(str(entry.get('acntCamp') or ''))
        if key not in existing:
            date = str(entry.get('date') or '')[:10]
            if not date:
                continue
            ws.upsert_match(
                key, date=date, recorded_date=date, status='draft',
                source='camp-context', match_type=match_type or 'training',
                competition_id=competition_id, own_team_id=own_team_id,
                enemy_team_id=opponent_team_id, own_side=own_side)
            saved += 1
        else:
            ws.stamp_capture_context(
                [key], competition_id=competition_id, match_type=match_type,
                own_team_id=own_team_id, enemy_team_id=opponent_team_id,
                own_side=own_side, source='camp-context')
            saved += 1
    return saved
