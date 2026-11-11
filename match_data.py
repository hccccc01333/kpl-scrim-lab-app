"""把赛后截图 OCR 与回放录屏 OCR 整理成一份单局数据包。

这一步只做“整理”：对齐同一局、统一字段名、保留来源和精度，不计算胜率或
分均指标。终局数据以赛后截图为准；录屏只提供过程曲线和快照。
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'kpl-match-data-v1'
VIDEO_SCHEMA = 'kpl-video-ocr-v1'
CAMPS = ('blue', 'red')
SIDES = ('left', 'right')


class MatchDataError(ValueError):
    """输入不属于同一局，或字段无法对齐。"""


def _cjk(text):
    return re.sub(r'[^\u4e00-\u9fff]', '', str(text or ''))


def _same_hero(a, b):
    left, right = _cjk(a), _cjk(b)
    if not left or not right:
        return False
    if left == right:
        return True
    return len(left) == len(right) >= 2 and sum(x != y for x, y in zip(left, right)) == 1


def _hero_of(row):
    return row.get('hero') or row.get('heroGuess')


def _lineup_heroes(rows):
    return [_hero_of(row) for row in rows if _hero_of(row)]


def _overlap(left, right):
    used, count = set(), 0
    for hero in left:
        for index, other in enumerate(right):
            if index not in used and _same_hero(hero, other):
                used.add(index)
                count += 1
                break
    return count


def load_video_report(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema') != VIDEO_SCHEMA:
        raise MatchDataError('不是 kpl-video-ocr-v1 报告')
    if not value.get('lineups') or not value.get('video'):
        raise MatchDataError('录屏报告缺少阵容或视频信息')
    return value


def load_postgame(path):
    path = Path(path)
    if path.suffix.lower() in ('.json',):
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or 'players' not in value:
            raise MatchDataError('赛后 JSON 不是截图识别结果')
        value.setdefault('sourceName', path.name)
        return value
    from ocr import recognize
    value = recognize(path.read_bytes())
    value['sourceName'] = path.name
    return value


def _display_value(field):
    if not isinstance(field, dict) or field.get('value') in (None, ''):
        return None
    text = str(field.get('value')).strip()
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([kK万]?)\s*(%?)', text)
    if not match:
        return {'raw': text, 'value': None, 'confidence': field.get('confidence')}
    number = float(match.group(1))
    unit = match.group(2)
    multiplier = {'k': 1000, 'K': 1000, '万': 10000}.get(unit, 1)
    value = number * multiplier
    if multiplier == 1 and match.group(3) == '' and '.' not in match.group(1):
        value = int(value)
    return {'raw': text, 'value': value, 'unit': unit or match.group(3) or None,
            'approx': bool(unit), 'confidence': field.get('confidence')}


def _field_value(player, key):
    field = (player.get('fields') or {}).get(key)
    return field.get('value') if isinstance(field, dict) else None


def _postgame_hero(player):
    field = (player.get('fields') or {}).get('hero') or {}
    return _cjk(field.get('value') or field.get('raw'))


def _page_heroes(page):
    return {side: [_postgame_hero(player) for player in page.get('players', []) if player.get('side') == side]
            for side in SIDES}


def _side_mapping(page, lineups):
    heroes = _page_heroes(page)
    blue, red = _lineup_heroes(lineups['blue']), _lineup_heroes(lineups['red'])
    direct = _overlap(heroes['left'], blue) + _overlap(heroes['right'], red)
    swapped = _overlap(heroes['left'], red) + _overlap(heroes['right'], blue)
    mapping = {'left': 'blue', 'right': 'red'} if direct >= swapped else {'left': 'red', 'right': 'blue'}
    score = max(direct, swapped)
    exact = (score == len(blue) + len(red) == 10)
    return mapping, score, 'exact' if exact else 'partial' if score else 'assumed'


def _postgame_date(value):
    match = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', str(value or ''))
    if not match:
        return None
    return {'year': int(match.group(1)), 'month': int(match.group(2)), 'day': int(match.group(3))}


def _postgame_duration(value):
    try:
        return round(float(value) * 60, 1)
    except (TypeError, ValueError):
        return None


def _match_video_meta(reports):
    first = reports[0]
    titles = {((report.get('match') or {}).get('title') or {}).get('value') for report in reports}
    titles.discard(None)
    title_warning = ('多路录屏的标题不同（可能是不同玩家的 POV）；按日期/时长/阵容校验同一局。'
                     if len(titles) > 1 else None)
    dates = [((report.get('match') or {}).get('date') or {}).get('value') for report in reports]
    dates = [value for value in dates if value]
    durations = [report.get('replayDuration') for report in reports if report.get('replayDuration')]
    date = dates[0] if dates else None
    if any((value.get('month'), value.get('day')) != (date.get('month'), date.get('day')) for value in dates):
        raise MatchDataError('多路录屏的日期不一致，可能不是同一局')
    date_value = ((first.get('match') or {}).get('date') or {}).get('value') or {}
    start_time = (date_value.get('text') or '').split(' ')[-1] if date_value.get('text') else None
    return {
        'title': ((first.get('match') or {}).get('title') or {}).get('value') or next(iter(titles), None),
        'mode': ((first.get('match') or {}).get('mode') or {}).get('value'),
        'date': date,
        'startTime': start_time,
        'duration': max(durations) if durations else None,
        'heroes': [hero for camp in CAMPS for hero in _lineup_heroes(first.get('lineups', {}).get(camp, []))],
        'warnings': [title_warning] if title_warning else [],
    }


def _postgame_meta(pages):
    dates = [_postgame_date((page.get('meta') or {}).get('date')) for page in pages]
    dates = [value for value in dates if value]
    durations = [_postgame_duration((page.get('meta') or {}).get('duration')) for page in pages]
    durations = [value for value in durations if value]
    if dates and any((value['year'], value['month'], value['day']) !=
                     (dates[0]['year'], dates[0]['month'], dates[0]['day']) for value in dates):
        raise MatchDataError('两张赛后截图的日期不一致')
    if durations and any(abs(value - durations[0]) > 2 for value in durations):
        raise MatchDataError('两张赛后截图的时长不一致')
    heroes = []
    for page in pages:
        for side in SIDES:
            heroes += [_postgame_hero(player) for player in page.get('players', []) if player.get('side') == side]
    heroes = list(dict.fromkeys(hero for hero in heroes if hero))
    return {'date': dates[0] if dates else None,
            'duration': durations[0] if durations else None,
            'heroes': heroes,
            'kinds': [page.get('kind') for page in pages]}


def check_identity(video_meta, postgame_meta):
    if not postgame_meta:
        return {'confidence': 'not-applicable', 'checks': {}, 'warnings': []}
    checks = {}
    if video_meta.get('date') and postgame_meta.get('date'):
        checks['date'] = (video_meta['date']['month'], video_meta['date']['day']) == \
                         (postgame_meta['date']['month'], postgame_meta['date']['day'])
    if video_meta.get('duration') and postgame_meta.get('duration'):
        checks['duration'] = abs(video_meta['duration'] - postgame_meta['duration']) <= 2
    if video_meta.get('heroes') and postgame_meta.get('heroes'):
        checks['heroes'] = _overlap(video_meta['heroes'], postgame_meta['heroes'])
    passed = sum(1 for value in checks.values() if value is True)
    if checks.get('heroes'):
        passed += 1 if checks['heroes'] >= 8 else 0
    hard_failure = checks.get('date') is False or checks.get('duration') is False
    if checks.get('heroes') is not None and checks['heroes'] < 8:
        hard_failure = True
    confidence = 'low' if hard_failure else 'high' if passed == 3 else 'medium' if passed >= 1 else 'low'
    warnings = []
    if checks.get('date') is False:
        warnings.append('录屏日期与赛后截图日期不一致。')
    if checks.get('duration') is False:
        warnings.append('录屏总时长与赛后截图时长不一致。')
    if checks.get('heroes') is not None and checks['heroes'] < 8:
        warnings.append(f"录屏阵容与赛后英雄只重合 {checks['heroes']}/10。")
    return {'confidence': confidence, 'checks': checks, 'warnings': warnings}


def _bundle_date(video_meta, postgame_meta):
    if postgame_meta and postgame_meta.get('date'):
        date = postgame_meta['date']
        return {'year': date['year'], 'month': date['month'], 'day': date['day'],
                'text': f"{date['year']:04d}-{date['month']:02d}-{date['day']:02d}"}
    if video_meta.get('date'):
        date = video_meta['date']
        return {'year': None, 'month': date['month'], 'day': date['day'],
                'text': f"{date['month']:02d}-{date['day']:02d}"}
    return None


def _nickname(row):
    value = row.get('nickname')
    confidence = row.get('nicknameConfidence')
    return value if value and (confidence is None or confidence >= 0.6) else None


def _match_key(video_meta, postgame_meta, identity=None):
    date_mismatch = bool(identity and (identity.get('checks') or {}).get('date') is False)
    date = postgame_meta.get('date') if postgame_meta and not date_mismatch else None
    if date:
        date_part = f"{date['year']:04d}{date['month']:02d}{date['day']:02d}"
    elif video_meta.get('date'):
        date_part = f"{video_meta['date']['month']:02d}{video_meta['date']['day']:02d}"
    else:
        date_part = 'unknown'
    duration = (video_meta.get('duration') or (postgame_meta or {}).get('duration') or 'na')
    heroes = sorted(_cjk(hero) for hero in video_meta.get('heroes', []) if hero)
    digest = hashlib.sha256('|'.join(heroes).encode('utf-8')).hexdigest()[:6]
    return f'{date_part}-{duration}-{digest}'


def _resolve_follow(label, lineups):
    if not label:
        return None
    matches = []
    for camp in CAMPS:
        for row in lineups.get(camp, []):
            if label == row.get('nickname') or _same_hero(label, _hero_of(row)):
                matches.append({'camp': camp, 'row': row})
    if len(matches) == 1:
        return matches[0]
    if not matches:
        # 允许只写英雄的一部分（如“孙”），但必须唯一。
        loose = []
        for camp in CAMPS:
            for row in lineups.get(camp, []):
                hero = _cjk(_hero_of(row))
                if label and (label in hero or (hero and hero in label)):
                    loose.append({'camp': camp, 'row': row})
        if len(loose) == 1:
            return loose[0]
        raise MatchDataError(f'没有唯一的 POV 队员：{label}')
    raise MatchDataError(f'POV 队员不唯一：{label}')


def _player_key(camp, row):
    slot = row.get('slot')
    if slot is not None:
        return f'{camp}-{slot}'
    panel = row.get('panelSlot')
    return f'{camp}-p{panel}' if panel is not None else f'{camp}-{_cjk(_hero_of(row))}'


def _roster_row(camp, hero, lineups):
    if not hero:
        return None
    matches = [row for row in lineups.get(camp, []) if _same_hero(hero, _hero_of(row))]
    return matches[0] if len(matches) == 1 else None


def _score_int(value):
    text = str(value).strip()
    return int(text) if text.isdigit() else value


def _merge_postgame(pages, lineups):
    if not pages:
        return {'players': [], 'scores': {}, 'unmatched': [], 'warnings': []}
    # 用英雄重合度最高的页面决定左右阵营映射，所有页面共用。
    primary = max(pages, key=lambda page: _side_mapping(page, lineups)[1])
    mapping, mapping_score, mapping_status = _side_mapping(primary, lineups)
    warnings = []
    if mapping_status != 'exact':
        warnings.append(f'赛后截图左右阵营按英雄重合映射（{mapping_status}，{mapping_score}/10）。')
    priority = {
        'kills': ('score', 'data'), 'deaths': ('score', 'data'), 'assists': ('score', 'data'),
        'damage': ('data', 'score'), 'taken': ('data', 'score'), 'participation': ('data', 'score'),
        'gold': ('data', 'score'), 'rating': ('data', 'score'), 'hero': ('score', 'data'),
    }
    buckets = {}
    for page in pages:
        for player in page.get('players', []):
            side = player.get('side')
            if side not in mapping:
                continue
            camp = mapping[side]
            slot = player.get('slot')
            hero = _postgame_hero(player)
            row = _roster_row(camp, hero, lineups)
            key = _player_key(camp, row) if row else f'{camp}-slot-{slot}'
            bucket = buckets.setdefault(key, {
                'camp': camp, 'postgameSlot': slot, 'rosterKey': key if row else None,
                'heroes': [], 'fields': {}, 'field_pages': {}, 'pages': [], 'visuals': [],
            })
            if row:
                bucket['rosterKey'] = key
            bucket['heroes'].append(hero)
            bucket['pages'].append(page.get('kind'))
            for name, field in (player.get('fields') or {}).items():
                if name in priority:
                    bucket['field_pages'].setdefault(name, []).append(
                        {'page': page.get('kind'), 'field': field})
            for visual in page.get('visuals', []):
                if visual.get('side') == side and visual.get('slot') == slot:
                    bucket['visuals'].append(visual)
    for key, bucket in buckets.items():
        for name, entries in bucket.pop('field_pages').items():
            order = priority.get(name, ('score', 'data'))
            chosen = next((entry for page in order for entry in entries
                           if entry['page'] == page and entry['field'].get('value') not in (None, '')), None)
            if chosen is None:
                chosen = entries[0]
            bucket['fields'][name] = {**chosen['field'], 'sourcePage': chosen['page']}
        heroes = list(dict.fromkeys(hero for hero in bucket['heroes'] if hero))
        bucket['hero'] = heroes[0] if heroes else None
        if len(heroes) > 1 and not all(_same_hero(heroes[0], hero) for hero in heroes[1:]):
            warnings.append(f'赛后两个页面的同一行英雄不一致：{" / ".join(heroes)}')
        if not bucket['rosterKey']:
            row = bucket['postgameSlot'] + 1 if isinstance(bucket['postgameSlot'], int) else '?'
            warnings.append(f'赛后一行未能匹配录屏阵容（{bucket["camp"]} 第 {row} 行）。')
    scores = {}
    for page in pages:
        if page.get('kind') == 'score' and page.get('scores'):
            left = page['scores'].get('left')
            right = page['scores'].get('right')
            if left not in (None, '') and right not in (None, ''):
                scores = {mapping['left']: _score_int(left), mapping['right']: _score_int(right)}
                break
    return {'players': list(buckets.values()), 'scores': scores,
            'mapping': mapping, 'mappingStatus': mapping_status,
            'unmatched': [], 'warnings': warnings}


def _attach_postgame(lineups, postgame):
    by_key = {}
    valid = {_player_key(camp, row): row for camp in CAMPS for row in lineups.get(camp, [])}
    for player in postgame['players']:
        key = player.get('rosterKey')
        if key in valid and key not in by_key:
            by_key[key] = player
            player['rosterKey'] = key
        elif key in by_key:
            player['reason'] = '同一队员在赛后截图出现两次'
            postgame['unmatched'].append(player)
            postgame['warnings'].append(f'{key} 在赛后截图出现两次，未自动合并。')
        else:
            player['reason'] = '赛后截图的行无法唯一匹配录屏阵容'
            postgame['unmatched'].append(player)
    return by_key


def _normalize_final(player, source):
    fields = {}
    for name, field in (player.get('fields') or {}).items():
        if name == 'hero':
            fields['hero'] = {**field, 'source': source}
        else:
            parsed = _display_value(field)
            if parsed:
                fields[name] = {**parsed, 'source': source,
                                'sourcePage': field.get('sourcePage')}
    skills = ['kills', 'deaths', 'assists']
    final = {'source': source, 'fields': fields,
             'kills': fields.get('kills', {}).get('value'),
             'deaths': fields.get('deaths', {}).get('value'),
             'assists': fields.get('assists', {}).get('value'),
             'totalGold': fields.get('gold', {}).get('value'),
             'damage': fields.get('damage', {}).get('value'),
             'taken': fields.get('taken', {}).get('value'),
             'participation': fields.get('participation', {}).get('value'),
             'rating': fields.get('rating', {}).get('value')}
    final['complete'] = all(final.get(key) is not None for key in
                            ('kills', 'deaths', 'assists', 'totalGold', 'damage', 'taken'))
    final['partial'] = not final['complete']
    equipment = []
    for slot in range(6):
        candidates = [visual for visual in player.get('visuals', [])
                      if visual.get('kind') == 'equipment' and visual.get('index') == slot]
        if candidates:
            equipment.append({'index': slot, 'status': candidates[0].get('status'),
                              'candidates': candidates[0].get('candidates', [])})
    if equipment:
        final['equipmentCandidates'] = equipment
    return final


def _merge_timeline(reports):
    buckets = {}
    for report in reports:
        source = (report.get('video') or {}).get('sha256', '')[:16]
        points = report.get('timeline') or []
        if not points:
            points = [{'gameTime': sample.get('gameTime'),
                       'blueKills': (sample.get('blue') or {}).get('kills', {}).get('value'),
                       'redKills': (sample.get('red') or {}).get('kills', {}).get('value'),
                       'blueGold': (sample.get('blue') or {}).get('gold', {}).get('value'),
                       'redGold': (sample.get('red') or {}).get('gold', {}).get('value')}
                      for sample in report.get('samples', [])]
        for point in points:
            time = point.get('gameTime')
            if time is None:
                continue
            bucket = buckets.setdefault(time, {'blueGold': [], 'redGold': [],
                                               'blueKills': [], 'redKills': [], 'sources': set()})
            for key in ('blueGold', 'redGold', 'blueKills', 'redKills'):
                if point.get(key) is not None:
                    bucket[key].append(point[key])
            bucket['sources'].add(source)
    def median(values):
        ordered = sorted(values)
        if not ordered:
            return None
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2
    timeline, warnings = [], []
    last = {'blueGold': None, 'redGold': None, 'blueKills': None, 'redKills': None}
    for time in sorted(buckets):
        bucket = buckets[time]
        row = {'gameTime': time, 'sources': len(bucket['sources'])}
        for key in ('blueGold', 'redGold', 'blueKills', 'redKills'):
            value = median(bucket[key])
            if value is None:
                row[key] = None
                continue
            if 'Kills' in key:
                value = int(round(value))
            if last[key] is not None and value < last[key]:
                row[key] = None
                warnings.append(f'{time}s 的 {key} 合并值回退，已丢弃。')
                continue
            row[key] = value
            last[key] = value
            if len(set(bucket[key])) > 1:
                spread = max(bucket[key]) - min(bucket[key])
                tolerance = max(60, (value or 0) * 0.03) if 'Gold' in key else 0
                if spread > tolerance:
                    row['disagree'] = True
                    warnings.append(f'{time}s 的 {key} 多路读数差 {spread}。')
        timeline.append(row)
    return timeline, list(dict.fromkeys(warnings))


def _kill_events(timeline):
    events, last = [], {'blue': None, 'red': None}
    for point in timeline:
        for camp in CAMPS:
            value = point.get(f'{camp}Kills')
            if value is None:
                continue
            if last[camp] is None:
                last[camp] = value
            elif value > last[camp]:
                events.append({'gameTime': point['gameTime'], 'camp': camp,
                               'delta': value - last[camp], 'after': value,
                               'precision': 'merged-timeline'})
                last[camp] = value
    return events


def _snapshot_players(snapshot, lineups):
    result = []
    for player in snapshot.get('players', []):
        camp = player.get('camp')
        if camp not in CAMPS:
            continue
        hero = player.get('hero')
        rows = [row for row in lineups[camp]
                if (player.get('slot') is not None and row.get('slot') == player.get('slot'))
                or (hero and _same_hero(hero, _hero_of(row)))]
        row = rows[0] if len(rows) == 1 else None
        result.append({'camp': camp, 'key': _player_key(camp, row) if row else None,
                       'hero': _hero_of(row) if row else hero,
                       'nickname': row.get('nickname') if row else player.get('nickname'),
                       'kda': player.get('kda'),
                       'kdaValidated': player.get('kdaValidated'),
                       'totalGold': player.get('gold')})
    return result


def _merge_scoreboard(reports, lineups):
    seen, snapshots, warnings = set(), [], []
    for report in reports:
        source = (report.get('video') or {}).get('sha256', '')[:16]
        for snapshot in (report.get('scoreboard') or {}).get('snapshots', []):
            if not snapshot.get('valid'):
                continue
            key = (snapshot.get('gameTime'), tuple(snapshot['blue'].get('values') or []),
                   tuple(snapshot['red'].get('values') or []))
            if key in seen:
                continue
            seen.add(key)
            snapshots.append({
                'gameTime': snapshot.get('gameTime'),
                'source': source,
                'kdaValidated': snapshot.get('kdaValidated'),
                'blue': {'sum': snapshot['blue'].get('sum'), 'team': snapshot['blue'].get('team'),
                         'values': snapshot['blue'].get('values'),
                         'kdaValues': [row['value'] if row else None
                                       for row in snapshot['blue'].get('kdaRows', [])]},
                'red': {'sum': snapshot['red'].get('sum'), 'team': snapshot['red'].get('team'),
                        'values': snapshot['red'].get('values'),
                        'kdaValues': [row['value'] if row else None
                                      for row in snapshot['red'].get('kdaRows', [])]},
                'players': _snapshot_players(snapshot, lineups),
            })
    snapshots.sort(key=lambda snapshot: snapshot['gameTime'] if snapshot['gameTime'] is not None else 0)
    if len({snapshot['gameTime'] for snapshot in snapshots}) != len(snapshots):
        warnings.append('同一局内出现多个相同时刻的记分板快照，已保留不同数值的快照。')
    return snapshots, warnings


def _game_time_at(samples, mapping, video_time):
    """视频时间 → 游戏时间：用最近时钟样本 + 播放速率外推。

    恒定 offset（game = video + offset）只在 1 倍速录屏成立；2 倍速时
    offset 随时间漂移，POV 片段的 gameStart/gameEnd 会偏出数分钟。
    最近样本外推在倍速、暂停、跳变下都更接近真实值；没有时钟样本时
    退回 offset。
    """
    if video_time is None:
        return None
    points = [(sample.get('videoTime'), sample.get('gameTime'))
              for sample in samples or []
              if sample.get('videoTime') is not None and sample.get('gameTime') is not None]
    offset = (mapping or {}).get('offset')
    if not points:
        return round(video_time + offset, 1) if offset is not None else None
    rate = (mapping or {}).get('speed') or 1.0
    nearest_video, nearest_game = min(points, key=lambda pair: abs(pair[0] - video_time))
    return round(nearest_game + (video_time - nearest_video) * rate, 1)


def _pov_series(report, follow, mapping=None):
    mapping = mapping or {}
    segments = (report.get('selection') or {}).get('segments', [])
    source = (report.get('video') or {}).get('sha256', '')[:16]
    pov = []
    for index, segment in enumerate(segments):
        start, end = segment.get('start'), segment.get('end')
        game_start = _game_time_at(report.get('samples'), mapping, start)
        game_end = _game_time_at(report.get('samples'), mapping, end)
        pov.append({
            'source': source, 'segment': index,
            'videoStart': start, 'videoEnd': end,
            'gameStart': game_start, 'gameEnd': game_end,
            'levelFirst': segment.get('levelFirst'), 'levelLast': segment.get('levelLast'),
            'kdaFirst': segment.get('kdaFirst'), 'kdaLast': segment.get('kdaLast'),
            'availableGoldFirst': segment.get('goldFirst'),
            'availableGoldLast': segment.get('goldLast'),
            'stats': segment.get('stats'), 'runes': segment.get('runes'),
            'equipment': segment.get('equipment'),
            'identity': 'manual' if follow else None,
        })
    series = []
    for sample in report.get('samples', []):
        selected = sample.get('selected')
        if not selected or sample.get('gameTime') is None:
            continue
        item = {
            'gameTime': sample.get('gameTime'),
            'level': (selected.get('level') or {}).get('value'),
            'kda': (selected.get('kda') or {}).get('value'),
            'availableGold': (selected.get('gold') or {}).get('value'),
            'stats': {key: (selected.get('stats') or {}).get(key, {}).get('value')
                      for key in ('attack', 'armor', 'magicAttack', 'magicResist')}
            if selected.get('stats') else None,
        }
        if selected.get('runes'):
            item['runes'] = selected['runes']
        if selected.get('equipment'):
            item['equipment'] = selected['equipment']
        series.append(item)
    return pov, series


def build_match_data(video_reports, follows=None, postgames=None, match_id=None, force=False):
    if not video_reports:
        raise MatchDataError('至少需要一份录屏报告')
    follows = list(follows or [])
    follows += [None] * (len(video_reports) - len(follows))
    postgames = list(postgames or [])
    video_meta = _match_video_meta(video_reports)
    postgame_meta = _postgame_meta(postgames) if postgames else None
    identity = check_identity(video_meta, postgame_meta)
    if postgames and identity['confidence'] == 'low' and not force:
        raise MatchDataError('录屏与赛后截图未通过同一局校验；确认后加 --force')
    lineups = video_reports[0].get('lineups', {})
    warnings = []
    warnings += video_meta.get('warnings', [])
    warnings += identity.get('warnings', [])
    if not postgames:
        warnings.append('未提供赛后截图；终局字段取自记分板快照，缺少伤害/承伤/参团率。')
    base_heroes = _lineup_heroes(lineups.get('blue', [])) + _lineup_heroes(lineups.get('red', []))
    for report in video_reports[1:]:
        other = _lineup_heroes((report.get('lineups') or {}).get('blue', [])) + \
            _lineup_heroes((report.get('lineups') or {}).get('red', []))
        overlap = _overlap(base_heroes, other)
        if overlap < 10:
            warnings.append(f"一路录屏阵容与首路只重合 {overlap}/10，请确认是否同一局。")
    postgame = _merge_postgame(postgames, lineups) if postgames else None
    if postgame:
        postgame_by_key = _attach_postgame(lineups, postgame)
    else:
        postgame_by_key = {}
    timeline, timeline_warnings = _merge_timeline(video_reports)
    snapshots, snapshot_warnings = _merge_scoreboard(video_reports, lineups)
    warnings += (postgame or {}).get('warnings', [])
    warnings += timeline_warnings + snapshot_warnings
    kinds = {page.get('kind') for page in postgames}
    if postgames and 'data' not in kinds:
        warnings.append('未提供赛后数据页，伤害/承伤/参团率不可用。')
    if postgames and 'score' not in kinds:
        warnings.append('未提供赛后战绩页，终局 KDA/经济可能不完整。')
    players, unattributed = [], []
    for camp in CAMPS:
        for row in lineups.get(camp, []):
            key = _player_key(camp, row)
            player = {'key': key, 'camp': camp, 'slot': row.get('slot'),
                      'panelSlot': row.get('panelSlot'), 'hero': _hero_of(row),
                      'heroStatus': row.get('heroStatus'), 'nickname': _nickname(row),
                      'nicknameRaw': row.get('nickname'),
                      'nicknameConfidence': row.get('nicknameConfidence'),
                      'final': None, 'process': {'pov': [], 'series': [], 'scoreboard': []},
                      'sources': []}
            final_player = postgame_by_key.get(key)
            if final_player:
                player['final'] = _normalize_final(final_player, 'postgame')
                player['sources'].append({'kind': 'postgame', 'pages': final_player.get('pages')})
            for snapshot in snapshots:
                for snapshot_player in snapshot.get('players', []):
                    if snapshot_player.get('key') != key:
                        continue
                    player['process']['scoreboard'].append({
                        'gameTime': snapshot['gameTime'], 'kda': snapshot_player.get('kda'),
                        'kdaValidated': snapshot_player.get('kdaValidated'),
                        'totalGold': snapshot_player.get('totalGold'), 'source': snapshot['source']})
            if player['final'] is None:
                latest = next((item for item in reversed(player['process']['scoreboard'])
                               if item.get('kda') or item.get('totalGold') is not None), None)
                if latest:
                    kda = latest.get('kda') or [None, None, None]
                    player['final'] = {'source': 'scoreboard', 'partial': True,
                                       'gameTime': latest['gameTime'],
                                       'kills': kda[0], 'deaths': kda[1], 'assists': kda[2],
                                       'totalGold': latest.get('totalGold'),
                                       'damage': None, 'taken': None,
                                       'participation': None, 'rating': None,
                                       'complete': False}
                    if postgames:
                        warnings.append(f'{key} 未匹配到赛后数据，终局字段用 {latest["gameTime"]}s 记分板快照，缺少伤害/承伤/参团率。')
                else:
                    warnings.append(f'{key} 没有可用的终局或记分板数据。')
            players.append(player)
    player_index = {player['key']: player for player in players}
    video_sources = []
    for report, follow in zip(video_reports, follows):
        resolved = _resolve_follow(follow, lineups)
        mapping = report.get('timeMapping') or {}
        pov, series = _pov_series(report, bool(resolved), mapping)
        follow_player = None
        if resolved:
            follow_player = {'camp': resolved['camp'], 'hero': _hero_of(resolved['row']),
                             'nickname': resolved['row'].get('nickname')}
        source = {'kind': 'video', 'file': (report.get('video') or {}).get('name'),
                  'sha256': (report.get('video') or {}).get('sha256'),
                  'followLabel': follow, 'followPlayer': follow_player,
                  'segments': len(pov)}
        video_sources.append({**source, 'selection': len(pov),
                              'coverage': report.get('coverage')})
        if not resolved:
            unattributed.append({**source, 'selection': pov, 'samples': len(series)})
            warnings.append(f"录屏 {source['file']} 没有 POV 标签，只用于团队曲线/记分板。")
            continue
        key = _player_key(resolved['camp'], resolved['row'])
        player = player_index.get(key)
        if not player:
            continue
        player['process']['pov'].extend(pov)
        player['process']['series'].extend(series)
        player['sources'].append({**source, 'selection': len(pov)})
        if len(pov) > 1:
            who = f"{follow_player['hero']}({follow_player['nickname'] or '昵称未知'})"
            warnings.append(f"{source['file']} 的 POV 标签 {follow} 解析为 {who}，"
                            f"但有 {len(pov)} 段观战目标切换，需人工确认。")
    duration = video_meta.get('duration')
    coverage_end = max((point['gameTime'] for point in timeline if point.get('gameTime') is not None),
                       default=None)
    coverage = {
        'videos': len(video_reports),
        'postgamePages': len(postgames),
        'players': len(players),
        'finalPlayers': sum(1 for player in players if player['final']),
        'povPlayers': sum(1 for player in players
                          if player['process']['pov'] or player['process']['series']),
        'scoreboardPlayers': sum(1 for player in players if player['process']['scoreboard']),
        'teamTimelinePoints': len(timeline),
        'scoreboardSnapshots': len(snapshots),
    }
    if duration and coverage_end is not None and coverage_end < duration - 2:
        warnings.append(f'录屏只覆盖到 {coverage_end // 60:02d}:{coverage_end % 60:02d}，'
                        f'总时长 {duration // 60:02d}:{duration % 60:02d}；团队曲线不是全场。')
    bundle = {
        'schema': SCHEMA,
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'match': {
            'key': match_id or _match_key(video_meta, postgame_meta, identity),
            'title': video_meta.get('title'), 'mode': video_meta.get('mode'),
            'date': _bundle_date(video_meta, postgame_meta),
            'startTime': video_meta.get('startTime'), 'duration': duration,
            'scores': (postgame or {}).get('scores', {}),
            'identity': identity,
            'videoCoverage': {'start': 0 if timeline else None, 'end': coverage_end,
                              'ratio': round(coverage_end / duration, 3)
                              if coverage_end is not None and duration else None},
        },
        'sources': video_sources
        + [{'kind': 'postgame', 'file': page.get('sourceName'), 'pageKind': page.get('kind'),
            'scores': page.get('scores'), 'meta': page.get('meta')} for page in postgames],
        'roster': {camp: [{'key': _player_key(camp, row), 'slot': row.get('slot'),
                           'panelSlot': row.get('panelSlot'), 'hero': _hero_of(row),
                           'heroStatus': row.get('heroStatus'), 'nickname': _nickname(row),
                           'nicknameRaw': row.get('nickname'),
                           'nicknameConfidence': row.get('nicknameConfidence')}
                          for row in lineups.get(camp, [])] for camp in CAMPS},
        'team': {'timeline': timeline, 'scoreboardSnapshots': snapshots,
                 'killEvents': _kill_events(timeline)},
        'players': players,
        'unattributedPov': unattributed,
        'postgameUnmatched': (postgame or {}).get('unmatched', []),
        'coverage': coverage,
        'warnings': list(dict.fromkeys(warnings)),
    }
    return bundle


def render_summary(bundle):
    match = bundle['match']
    date = match.get('date') or {}
    duration = match.get('duration')
    duration_text = (f"{int(duration) // 60:02d}:{int(duration) % 60:02d}"
                     if isinstance(duration, (int, float)) else '?')
    lines = [f"单局数据包：{match['key']}",
             f"比赛：{match.get('title') or '标题未知'} · {match.get('mode') or '模式未知'} · "
             f"{date.get('text') or '日期未知'} · {duration_text}"]
    identity = match.get('identity') or {}
    lines.append(f"同一局校验：{identity.get('confidence')} {identity.get('checks')}")
    lines.append(f"来源：视频 {bundle['coverage']['videos']} 路，赛后 {bundle['coverage']['postgamePages']} 张")
    for camp, label in (('blue', '蓝'), ('red', '红')):
        rows = bundle['roster'].get(camp, [])
        lines.append(f"阵容{label}：" + '  '.join(
            f"{row.get('hero') or '?'}({row.get('nickname') or '?'})" for row in rows))
    coverage = bundle['coverage']
    lines.append(f"过程覆盖：时间轴 {coverage['teamTimelinePoints']} 点，记分板 {coverage['scoreboardSnapshots']} 快照，"
                 f"POV {coverage['povPlayers']} 人，终局 {coverage['finalPlayers']} 人")
    scores = match.get('scores') or {}
    if scores:
        lines.append(f"终局比分：蓝 {scores.get('blue', '?')} / 红 {scores.get('red', '?')}")

    def number(value):
        return int(value) if isinstance(value, float) and value.is_integer() else value

    for player in bundle['players']:
        final = player.get('final') or {}
        kda = '/'.join(str(final.get(key)) if final.get(key) is not None else '?'
                       for key in ('kills', 'deaths', 'assists'))
        gold = number(final.get('totalGold'))
        damage = number(final.get('damage'))
        suffix = ''
        if final.get('partial') and final.get('source') == 'scoreboard' and final.get('gameTime') is not None:
            suffix = f"（快照 {final['gameTime'] // 60:02d}:{final['gameTime'] % 60:02d}）"
        elif final.get('partial'):
            suffix = '（部分）'
        parts = [f"{player['camp']} {player.get('hero') or '?'} {kda}{suffix}"]
        if gold is not None:
            parts.append(f"经济 {gold}")
        if damage is not None:
            parts.append(f"伤害 {damage}")
        lines.append('  ' + ' · '.join(parts))
    for warning in bundle['warnings']:
        lines.append(f'注意：{warning}')
    return '\n'.join(lines)
