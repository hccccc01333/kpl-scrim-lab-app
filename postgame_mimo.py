"""Mimo refinement for tabbed post-game screenshots.

The fast layout engine in :mod:`postgame_ocr` produces the immediate result.
This module asks the local Xiaomi-OCR-0 model for a page-specific JSON
transcription and merges it conservatively:

* missing fields may be filled from Mimo;
* two disagreeing numbers stay as the fast engine's value, with the Mimo
  alternative and a warning attached;
* exact hero names may correct an uncertain/auto-matched hero, but a manual
  hero choice is never overwritten;
* everything remains a candidate for human review.
"""
import re

import mimo_ocr
import postgame_ocr as fast_ocr
from screenshot_schema import (FIELD_UNITS, MATCH_PAGE_FIELDS, PAGE_FIELDS,
                               PLAYER_FIELDS, SHARE_FIELDS, TABS)

PROMPT_VERSION = 'postgame-rows-v3'
DEFAULT_MAX_TOKENS = 700
MIMO_VERSION = 'mimo-postgame-v3'

def _json(value):
    import json
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


IDENTITY = ('nickname', 'hero', 'rating', 'title', 'mvp')
CORE_FIELDS = ('kills', 'deaths', 'assists', 'gold', 'damageDealt', 'damageTaken',
               'participation')
CORE_SHARES = ('outputShare', 'takenShare', 'goldShare')
PAGE_HINTS = {
    'score': '战绩页（装备型）：胜负、日期、时长、KDA、经济',
    'kda': '战绩页（KDA 占比型）：击败、死亡、助攻和占比',
    'data': '数据页：输出伤害、承受伤害、总经济、参团率',
    'output': '输出页：输出伤害、伤害转化比、输出占比',
    'survival': '生存页：承受伤害、每死承伤、承伤占比',
    'farming': '发育页：总经济、野怪经济、补刀数',
    'team': '团队页：参团率、控制效果、治疗量、对塔伤害',
    'unknown': '未能确定页签；请同时判断页签并读取可见核心字段',
}


def _values_for(page):
    if page in PAGE_FIELDS:
        fields = [field for field in PAGE_FIELDS[page]
                  if field not in IDENTITY and field not in SHARE_FIELDS]
        shares = [field for field in PAGE_FIELDS[page] if field in SHARE_FIELDS]
    else:
        fields, shares = list(CORE_FIELDS), list(CORE_SHARES)
    return fields, shares


def _field_order(page):
    fields, shares = _values_for(page)
    return list(fields) + list(shares)


def _max_tokens(page):
    count = 5 + len(_field_order(page))
    return max(360, min(900, 80 + 10 * count * 3))


def build_prompt(page):
    order = '|'.join(('nickname', 'hero', 'rating', 'mvp', 'title') + tuple(_field_order(page)))
    lines = [
        'Read this Honor of Kings post-game screenshot. '
        f'Expected tab: {PAGE_HINTS.get(page, PAGE_HINTS["unknown"])}',
    ]
    if page == 'score':
        lines.append('First output one header line: '
                     'MATCH|date|time|durationSec|mode|result|scoreLeft|scoreRight')
    elif page == 'unknown':
        lines.append('First output one page line: PAGE|<score|kda|data|output|survival|farming|team|unknown>')
    lines.extend([
        'Then output exactly 10 player rows in reading order: left side 5 rows '
        'top-to-bottom, then right side 5 rows top-to-bottom.',
        'One row per line, fields separated by "|" in this exact order:',
        order,
        'Rules:',
        '- nickname, hero, title: copy printed text exactly; use - if unreadable.',
        '- rating: one decimal. mvp: 1 or 0. title: use - if none.',
        '- Replace any | inside a nickname with a space.',
        '- damageDealt/damageTaken/gold: convert 59.2k -> 59200 and 5.9万 -> 59000.',
        '- participation/shares: 0-100 without %. durationSec: total seconds (18:52 -> 1132).',
        '- date: YYYY-MM-DD. result: win or loss. score: two integers.',
        '- Use - for missing or unreadable values.',
        '- Output only the lines above. No column header, numbering, markdown or commentary.',
    ])
    return '\n'.join(lines)


def parse_response(text, page):
    """Parse either the compact pipe format or a JSON fallback.

    Returns ``{'format', 'pageType', 'match', 'players', 'warnings'}``.  Player
    rows use flat field keys so the same merge path works for both formats.
    """
    warnings = []
    cleaned = re.sub(r'<think>.*?</think>', '', str(text or ''), flags=re.S)
    if '{' in cleaned and '"players"' in cleaned:
        value, error = mimo_ocr.parse_json(cleaned)
        if isinstance(value, dict) and isinstance(value.get('players'), list):
            return {'format': 'json', 'pageType': value.get('pageType'),
                    'match': value.get('match') or value.get('header') or {},
                    'players': value['players'], 'warnings': warnings}
        if error:
            warnings.append(f'JSON 解析失败，尝试逐行格式：{error}')

    values = _field_order(page)
    expected = 5 + len(values)
    rows, match, parsed_page = [], {}, None
    for raw in cleaned.splitlines():
        line = raw.strip().strip('`').strip()
        if not line:
            continue
        if line.startswith('MATCH|') or line.startswith('MATCH:'):
            match = _parse_match_line(line)
            continue
        if line.startswith('PAGE|') or line.startswith('PAGE:'):
            parsed_page = re.split(r'[|:]', line, maxsplit=1)[-1].strip()
            continue
        line = re.sub(r'^\s*(?:[-*•]|\d{1,2}[.)、])\s*', '', line)
        if not line or line.lower().startswith(('nickname|', 'nickname\t', '昵称|', '昵称\t')):
            continue
        parts = [part.strip() for part in re.split(r'\s*[|｜]\s*', line)]
        if len(parts) == 1 and '\t' in line:
            parts = [part.strip() for part in line.split('\t')]
        if len(parts) == 1 and not any(mark in line for mark in ('|', '｜', '\t')):
            # Last resort: accept comma-separated rows, but never split a normal line.
            if line.count(',') >= expected - 2 or line.count('，') >= expected - 2:
                parts = [part.strip() for part in re.split(r'[,，]', line)]
        explicit_side = None
        if parts and parts[0].lower() in ('left', 'right', 'blue', 'red', '蓝', '红',
                                          '蓝方', '红方', '左侧', '右侧'):
            explicit_side = 'left' if parts[0].lower() in ('left', 'blue', '蓝', '蓝方', '左侧') else 'right'
            parts = parts[1:]
        if not parts:
            continue
        if len(parts) < expected:
            parts += ['-'] * (expected - len(parts))
        elif len(parts) > expected:
            warnings.append(f'一行返回 {len(parts)} 列（应为 {expected} 列），已截断多余列。')
            parts = parts[:expected]
        row = {'nickname': parts[0], 'hero': parts[1], 'rating': parts[2],
               'mvp': parts[3], 'title': parts[4]}
        for key, value in zip(values, parts[5:]):
            row[key] = value
        rows.append({'row': row, 'side': explicit_side})
    players = _assign_rows(rows)
    if len(players) != 10:
        warnings.append(f'Mimo 返回 {len(players)} 行（应为 10 行）；只合并读出的行。')
    return {'format': 'rows', 'pageType': parsed_page, 'match': match,
            'players': players, 'warnings': warnings}


def _assign_rows(rows):
    counters = {'left': 0, 'right': 0}
    players = []
    for index, item in enumerate(rows):
        row = item['row']
        side = item.get('side')
        if side not in ('left', 'right'):
            side = 'left' if index < 5 else 'right'
        slot = counters[side]
        counters[side] += 1
        if slot >= 5:
            continue
        players.append({
            'side': side, 'slot': slot,
            'nickname': row.get('nickname'),
            'hero': row.get('hero'),
            'rating': row.get('rating'),
            'mvp': _parse_mvp(row.get('mvp')),
            'title': row.get('title'),
            **{key: value for key, value in row.items()
               if key not in ('nickname', 'hero', 'rating', 'mvp', 'title')},
        })
    return players


def _parse_mvp(value):
    text = str(value or '').strip().lower()
    return text in ('1', 'true', 'yes', '是', 'mvp', '√')


def _parse_match_line(line):
    parts = [part.strip() for part in re.split(r'\s*[|｜]\s*', line)]
    if len(parts) < 8:
        parts += [''] * (8 - len(parts))
    date, _ = _match_value('date', parts[1])
    clock, _ = _match_value('time', parts[2])
    duration, _ = _match_value('durationSec', parts[3])
    mode, _ = _match_value('mode', parts[4])
    result, _ = _match_value('result', parts[5])
    return {'date': date, 'time': clock, 'durationSec': duration, 'mode': mode,
            'result': result,
            'score': {'left': mimo_ocr.clean_number(parts[6], 'int'),
                      'right': mimo_ocr.clean_number(parts[7], 'int')}}


COLUMN_PROMPT_VERSION = 'postgame-columns-v1'
HERO_PROMPT = (
    'This image is the hero-name column of a Honor of Kings post-game table. '
    'Read the five Chinese hero names from top to bottom, one per line, exactly as printed. '
    'No numbering, no bullets, no extra text.'
)
NICKNAME_PROMPT = (
    'This image is a column of printed player nicknames from a Honor of Kings post-game table. '
    'Read the five nicknames from top to bottom, one per line, exactly as printed. '
    'Ignore numbers, percentages and hero names. No numbering, no extra text.'
)
HEADER_PROMPT = (
    'Read the top header of this Honor of Kings post-game screenshot. Return one compact JSON '
    'object with keys date, time, durationSec, mode, result, scoreLeft, scoreRight. '
    'date is YYYY-MM-DD; durationSec is total seconds; result is win or loss; score is integers. '
    'Use null for fields that are not visible. No markdown.'
)


def refine(data, result, name=None, on_stage=None, force=False, mode='columns'):
    """Run Mimo on one page and return a refined copy of ``result``.

    Default mode reads the printed hero and nickname columns; that is where the
    fast layout engine loses characters and where short Mimo prompts are most
    reliable.  ``mode='page'`` keeps the whole-page fallback for experiments.
    """
    if mode == 'page':
        return _refine_page(data, result, name=name, on_stage=on_stage, force=force)
    from vision import prepare_image
    image, _ = prepare_image(data)
    page = result.get('pageType') or 'unknown'
    response = {'engine': mimo_ocr.ENGINE, 'model': mimo_ocr.MODEL_REPO,
                'cached': True, 'elapsedMs': 0, 'calls': 0, 'device': None,
                'texts': {}}
    parsed_players = []
    warnings = []
    try:
        for side in ('left', 'right'):
            players = [player for player in (result.get('players') or [])
                       if player.get('side') == side]
            if not players:
                continue
            hero_crop = _column_crop(image, side, players, 'hero')
            if on_stage:
                on_stage(f'Mimo 读取{"左" if side == "left" else "右"}侧英雄名…')
            hero_response = mimo_ocr.get_engine().read(
                hero_crop, HERO_PROMPT, max_new_tokens=100,
                cache=not force, cache_tag=f'{COLUMN_PROMPT_VERSION}:hero:{side}',
                on_stage=on_stage)
            response['calls'] += 1
            response['cached'] = response['cached'] and bool(hero_response.get('cached'))
            response['elapsedMs'] += hero_response.get('elapsedMs') or 0
            response['device'] = hero_response.get('device') or response['device']
            response['texts'][f'{side}-hero'] = hero_response.get('text') or ''
            heroes = _name_rows(hero_response.get('text') or '', 'hero')
            nickname_crop = _column_crop(image, side, players, 'nickname')
            if on_stage:
                on_stage(f'Mimo 读取{"左" if side == "left" else "右"}侧昵称…')
            nickname_response = mimo_ocr.get_engine().read(
                nickname_crop, NICKNAME_PROMPT, max_new_tokens=100,
                cache=not force, cache_tag=f'{COLUMN_PROMPT_VERSION}:nickname:{side}',
                on_stage=on_stage)
            response['calls'] += 1
            response['cached'] = response['cached'] and bool(nickname_response.get('cached'))
            response['elapsedMs'] += nickname_response.get('elapsedMs') or 0
            response['texts'][f'{side}-nickname'] = nickname_response.get('text') or ''
            nicknames = _name_rows(nickname_response.get('text') or '', 'nickname')
            if len(heroes) != len(players):
                warnings.append(f'{"左" if side == "left" else "右"}侧 Mimo 读出 '
                                f'{len(heroes)} 个英雄名（应为 {len(players)} 行）；按名字匹配，不按位置补齐。')
            if len(nicknames) != len(players):
                warnings.append(f'{"左" if side == "left" else "右"}侧 Mimo 读出 '
                                f'{len(nicknames)} 个昵称（应为 {len(players)} 行）；按名字匹配，不按位置补齐。')
            parsed_players.extend(_assign_columns(players, heroes, nicknames))
        header = None
        if page == 'unknown' or (page == 'score' and not (result.get('match') or {}).get('date')):
            header_crop = image.crop((0, 0, image.width, round(image.height * .13)))
            if on_stage:
                on_stage('Mimo 读取页头日期/时长…')
            header_response = mimo_ocr.get_engine().read(
                header_crop, HEADER_PROMPT, max_new_tokens=120,
                cache=not force, cache_tag=f'{COLUMN_PROMPT_VERSION}:header',
                on_stage=on_stage)
            response['calls'] += 1
            response['cached'] = response['cached'] and bool(header_response.get('cached'))
            response['elapsedMs'] += header_response.get('elapsedMs') or 0
            response['texts']['header'] = header_response.get('text') or ''
            header = _header_from_text(header_response.get('text') or '')
    except mimo_ocr.MimoUnavailable as error:
        output = _copy(result)
        output.setdefault('warnings', []).append(f'Mimo 精读不可用：{error}')
        output['mimo'] = {'engine': mimo_ocr.ENGINE, 'version': MIMO_VERSION,
                          'available': False, 'error': str(error)}
        return output
    if not parsed_players:
        output = _copy(result)
        output.setdefault('warnings', []).append('Mimo 精读没有读出有效选手行，保留快速识别结果。')
        output['mimo'] = {'engine': mimo_ocr.ENGINE, 'version': MIMO_VERSION,
                          'available': True, 'raw': response.get('texts'),
                          'error': 'no player rows'}
        return output
    response['text'] = _json(response.get('texts') or {})
    parsed = {'format': 'columns', 'pageType': page if page != 'unknown' else None,
              'match': header or {}, 'players': parsed_players, 'warnings': warnings}
    output = merge_result(result, parsed, response, name=name)
    if isinstance(output.get('mimo'), dict):
        output['mimo']['columns'] = {
            'hero': [key for key in (response.get('texts') or {}) if key.endswith('-hero')],
            'nickname': [key for key in (response.get('texts') or {}) if key.endswith('-nickname')],
            'prompt': COLUMN_PROMPT_VERSION,
        }
    return output


def _refine_page(data, result, name=None, on_stage=None, force=False):
    from vision import prepare_image
    image, _ = prepare_image(data)
    page = result.get('pageType') or 'unknown'
    prompt = build_prompt(page)
    try:
        response = mimo_ocr.get_engine().read(
            image, prompt, max_new_tokens=_max_tokens(page),
            cache=not force, cache_tag=f'{PROMPT_VERSION}:{page}', on_stage=on_stage)
    except mimo_ocr.MimoUnavailable as error:
        output = _copy(result)
        output.setdefault('warnings', []).append(f'Mimo 精读不可用：{error}')
        output['mimo'] = {'engine': mimo_ocr.ENGINE, 'version': MIMO_VERSION,
                          'available': False, 'error': str(error)}
        return output
    parsed = parse_response(response.get('text') or '', page)
    parsed['warnings'] = list(parsed.get('warnings') or [])
    if not parsed.get('players'):
        output = _copy(result)
        output.setdefault('warnings', []).append('Mimo 精读没有读出有效选手行，保留快速识别结果。')
        output['mimo'] = {
            'engine': mimo_ocr.ENGINE, 'version': MIMO_VERSION, 'available': True,
            'cached': response.get('cached'), 'elapsedMs': response.get('elapsedMs'),
            'raw': (response.get('text') or '')[:20000],
            'format': parsed.get('format'),
            'error': 'no player rows',
        }
        return output
    return merge_result(result, parsed, response, name=name)


def _assign_columns(players, heroes, nicknames):
    """Zip only when a side read all rows; otherwise match by existing names."""
    players = sorted(players, key=lambda item: item['slot'])
    rows = [{'side': player['side'], 'slot': player['slot']} for player in players]
    if heroes and len(heroes) == len(players):
        for index, hero in enumerate(heroes):
            rows[index]['hero'] = hero
    else:
        for hero in heroes:
            index = _existing_index(players, 'hero', hero)
            if index is not None:
                rows[index]['hero'] = hero
    if nicknames and len(nicknames) == len(players):
        for index, nickname in enumerate(nicknames):
            rows[index]['nickname'] = nickname
    else:
        unmatched = []
        for nickname in nicknames:
            index = _existing_index(players, 'nickname', nickname)
            if index is not None:
                rows[index]['nickname'] = nickname
            else:
                unmatched.append(nickname)
        missing = [index for index, player in enumerate(players)
                   if not (player.get('nickname') or {}).get('value')]
        if len(missing) == 1 and len(unmatched) == 1:
            rows[missing[0]]['nickname'] = unmatched[0]
    return rows


def _existing_index(players, kind, value):
    target = _norm(value)
    if not target:
        return None
    matches = []
    for index, player in enumerate(players):
        if kind == 'hero':
            current = (player.get('hero') or {}).get('value')
            candidates = [item.get('name') for item in (player.get('heroCandidates') or [])]
            if target == _norm(current) or target in {_norm(item) for item in candidates}:
                matches.append(index)
        else:
            current = (player.get('nickname') or {}).get('value')
            if target == _norm(current):
                matches.append(index)
    return matches[0] if len(matches) == 1 else None


def _column_crop(image, side, players, kind):
    from PIL import Image
    width, height = image.size
    centers = []
    for player in players:
        box = (player.get('rating') or {}).get('box') or (player.get('hero') or {}).get('box')
        if not box:
            continue
        ys = [point[1] for point in box]
        centers.append(sum(ys) / len(ys))
    if len(centers) >= 2:
        y1, y2 = min(centers) - .06, max(centers) + .06
    else:
        y1, y2 = .18, .94
    y1, y2 = max(0, y1), min(1, y2)
    if kind == 'hero':
        x1, x2 = (.0, .145) if side == 'left' else (.49, .635)
    else:
        x1, x2 = (.08, .42) if side == 'left' else (.60, .94)
    box = (round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height))
    area = image.crop(box)
    return area.resize((area.width * 2, area.height * 2), Image.Resampling.LANCZOS)


def _name_rows(text, kind):
    """Read five short names from JSON, one-per-line text, or catalog mentions."""
    cleaned = re.sub(r'<think>.*?</think>', '', str(text or ''), flags=re.S)
    value, _ = mimo_ocr.parse_json(cleaned)
    rows = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                rows.append(item)
            elif isinstance(item, dict):
                for key in (('hero', 'name', 'value') if kind == 'hero'
                            else ('nickname', 'name', 'value')):
                    if item.get(key):
                        rows.append(str(item[key]))
                        break
    elif isinstance(value, dict):
        for key in ('rows', 'players', 'names', 'items'):
            items = value.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        rows.append(item)
                    elif isinstance(item, dict):
                        for field in (('hero', 'name', 'value') if kind == 'hero'
                                      else ('nickname', 'name', 'value')):
                            if item.get(field):
                                rows.append(str(item[field]))
                                break
                break
    entries = fast_ocr.catalog()['entries'] if hasattr(fast_ocr, 'catalog') else []
    names = sorted((entry['name'] for entry in entries if entry['kind'] == 'hero'),
                   key=len, reverse=True)
    name_set = set(names)
    if not rows:
        for raw in cleaned.splitlines():
            line = raw.strip().strip('`').strip()
            if not line:
                continue
            line = re.sub(r'^\s*(?:[-*•]|\d{1,2}[.)、])\s*', '', line)
            line = re.sub(r'^\s*["“]|["”]\s*$', '', line)
            if not line:
                continue
            if re.search(r'[|｜]', line):
                line = re.split(r'\s*[|｜]\s*', line)[0]
            if any(mark in line for mark in (',', '，', '、')):
                parts = [part.strip() for part in re.split(r'[,，、]', line) if part.strip()]
                rows.extend(parts)
            else:
                tokens = [token for token in re.split(r'\s+', line) if token.strip()]
                if 2 <= len(tokens) <= 5 and _plausible_names(tokens, kind, name_set):
                    rows.extend(tokens)
                else:
                    rows.append(line)
    if kind == 'hero':
        rows = [re.sub(r'\s+', '', str(item)).strip('"“”') for item in rows]
    else:
        rows = [str(item).strip().strip('"“”') for item in rows]
    rows = [item for item in rows if item and item not in ('-', '—')]
    if kind == 'hero' and len(rows) < 5:
        joined = ''.join(rows)
        for match in re.finditer('|'.join(re.escape(name) for name in names), joined):
            if match.group(0) not in rows:
                rows.append(match.group(0))
    return rows[:5]


def _plausible_names(tokens, kind, hero_names):
    if kind == 'hero':
        if any(token in hero_names for token in tokens):
            return True
        return all(re.fullmatch(r'[\u4e00-\u9fff]{1,6}', token) for token in tokens)
    if any(re.fullmatch(r'[\d.%/:]+', token) for token in tokens):
        return False
    return all(1 <= len(token) <= 16 for token in tokens)


def _header_from_text(text):
    value, _ = mimo_ocr.parse_json(text)
    if not isinstance(value, dict):
        value = {}
    score = _parse_score(value.get('score') or {
        'left': value.get('scoreLeft'), 'right': value.get('scoreRight')})
    duration = _match_value('durationSec', value.get('durationSec'))[0]
    if duration is not None and duration <= 60:
        duration = None
    mode = _match_value('mode', value.get('mode'))[0]
    if mode in ('双方', '对位', '返回队伍', '未开始匹配'):
        mode = None
    return {
        'date': _match_value('date', value.get('date'))[0],
        'time': _match_value('time', value.get('time'))[0],
        'durationSec': duration,
        'mode': mode,
        'result': _match_value('result', value.get('result'))[0],
        'score': score,
    }


def merge_result(result, parsed, response=None, name=None):
    """Merge a parsed Mimo JSON object into a fast OCR result."""
    from hero_names import resolve_name
    from vision import catalog

    response = response or {}
    output = _copy(result)
    warnings = list(output.get('warnings') or [])
    warnings.extend(parsed.get('warnings') or [])
    stats = {'filled': 0, 'agreed': 0, 'conflicts': 0, 'playersAdded': 0,
             'heroes': 0, 'nicknames': 0}
    entries = catalog()['entries']
    hero_names = {entry['name'] for entry in entries if entry['kind'] == 'hero'}

    page = _page_type(parsed.get('pageType'), output.get('pageType'))
    current_page = output.get('pageType')
    if current_page not in PAGE_FIELDS and page in PAGE_FIELDS:
        output['pageType'] = page
        warnings.append(f'快速识别未判断页签，Mimo 判断为 {page}；字段按该页签合并，仍需核对。')
    elif page != current_page:
        warnings.append(f'Mimo 判断页签为 {page}，快速识别为 {current_page}；已保留快速页签并核对字段。')
    output['tab'] = TABS.get(output.get('pageType'), output.get('tab'))

    match = parsed.get('match') or parsed.get('header') or {}
    _merge_match(output, match, output.get('pageType') or page, warnings, stats)
    parsed_players = parsed.get('players')
    if isinstance(parsed_players, dict):
        parsed_players = list(parsed_players.values())
    if not isinstance(parsed_players, list):
        parsed_players = []
    if len(parsed_players) != 10:
        warnings.append(f'Mimo 返回 {len(parsed_players)} 行（应为 10 行）；只合并可确认的 side/slot。')

    by_key = {(player['side'], player['slot']): player for player in output.get('players') or []}
    one_based = _one_based_slots(parsed_players)
    for index, item in enumerate(parsed_players):
        if not isinstance(item, dict):
            continue
        key = _player_key(item, index, parsed_players, one_based)
        if key is None:
            continue
        side, slot = key
        target = by_key.get((side, slot))
        if target is None:
            target = _new_player(side, slot)
            output.setdefault('players', []).append(target)
            by_key[(side, slot)] = target
            stats['playersAdded'] += 1
            warnings.append(f'Mimo 补出 {_side_label(side)}{slot + 1} 行，需人工核对。')
        _merge_player(target, item, output.get('pageType') or page, warnings, stats,
                      entries, hero_names, resolve_name)
    output['players'].sort(key=lambda item: (item['side'] != 'left', item['slot']))

    output['coverage'] = fast_ocr._coverage(output.get('players') or [])
    fast_ocr._validate_scores(output.get('match') or {}, output.get('players') or [],
                              output.get('pageType'), warnings)
    output['warnings'] = _dedupe(warnings)
    output['engine'] = {
        'layout': 'rapidocr-onnxruntime',
        'refine': mimo_ocr.ENGINE,
        'mode': 'hybrid',
        'prompt': PROMPT_VERSION,
    }
    output['refineVersion'] = MIMO_VERSION
    output['mimo'] = {
        'engine': mimo_ocr.ENGINE,
        'model': response.get('model'),
        'version': MIMO_VERSION,
        'prompt': PROMPT_VERSION,
        'available': True,
        'cached': bool(response.get('cached')),
        'elapsedMs': response.get('elapsedMs'),
        'device': response.get('device'),
        'pageType': parsed.get('pageType'),
        'players': len(parsed_players),
        'format': parsed.get('format'),
        'stats': stats,
        'raw': (response.get('text') or '')[:20000],
    }
    return output


def _copy(result):
    import copy
    return copy.deepcopy(result)


def _page_type(value, fallback):
    value = str(value or '').strip().lower()
    tabs = {'战绩': 'score', '数据': 'data', '输出': 'output', '生存': 'survival',
            '发育': 'farming', '团队': 'team'}
    value = tabs.get(str(value or '').strip(), value)
    if value in PAGE_FIELDS:
        return value
    return fallback if fallback in PAGE_FIELDS else 'unknown'


def _one_based_slots(players):
    slots = []
    for item in players:
        if not isinstance(item, dict) or item.get('slot') is None:
            return False
        try:
            slots.append(int(item.get('slot')))
        except (TypeError, ValueError):
            return False
    return bool(slots) and all(1 <= slot <= 5 for slot in slots)


def _player_key(item, index, players, one_based=False):
    side = str(item.get('side') or '').strip().lower()
    if side in ('blue', '蓝', '蓝方', '左侧'):
        side = 'left'
    elif side in ('red', '红', '红方', '右侧'):
        side = 'right'
    if side not in ('left', 'right'):
        side = 'left' if index < 5 else 'right'
    try:
        slot = int(item.get('slot', index % 5))
    except (TypeError, ValueError):
        slot = index % 5
    if one_based:
        slot -= 1
    if not 0 <= slot < 5:
        slot = index % 5
    return side, slot


def _new_player(side, slot):
    return {
        'side': side, 'slot': slot, 'nickname': None, 'hero': None,
        'heroStatus': 'unreadable', 'heroCandidates': [], 'heroReadings': [],
        'rating': None, 'title': None, 'mvp': False, 'fields': {}, 'shares': {},
        'sources': ['mimo'],
    }


def _merge_match(output, source, page, warnings, stats):
    target = output.setdefault('match', {})
    for key in ('date', 'time', 'durationSec', 'mode', 'result'):
        if key not in MATCH_PAGE_FIELDS.get(page, ()) and page != 'unknown':
            continue
        value, raw = _match_value(key, source.get(key))
        if value is None:
            continue
        if target.get(key) is None:
            target[key] = value
            stats['filled'] += 1
        elif target[key] != value:
            warnings.append(f'{page} 页 {key} 快速识别 {target[key]} / Mimo {value}')
            stats['conflicts'] += 1
    score = _parse_score(source.get('score'))
    for side in ('left', 'right'):
        value = score.get(side)
        if value is None:
            continue
        current = (target.get('score') or {}).get(side)
        if current is None:
            target.setdefault('score', {})[side] = value
            stats['filled'] += 1
        elif current != value:
            warnings.append(f'{page} 页比分 {side} 快速识别 {current} / Mimo {value}')
            stats['conflicts'] += 1


def _match_value(key, value):
    raw = value
    if value is None:
        return None, None
    if key == 'date':
        match = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', str(value))
        if not match:
            return None, None
        return '-'.join([match.group(1), match.group(2).zfill(2), match.group(3).zfill(2)]), raw
    if key == 'time':
        match = re.search(r'(\d{1,2}):(\d{2})', str(value))
        if not match:
            return None, None
        return f'{int(match.group(1)):02d}:{match.group(2)}', raw
    if key == 'durationSec':
        if isinstance(value, (int, float)):
            return int(value), raw
        text = str(value)
        match = re.search(r'(\d{1,2})\s*[:：]\s*(\d{2})', text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2)), raw
        match = re.search(r'(\d{1,3})\s*分\s*(\d{1,2})', text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2)), raw
        try:
            return int(float(text)), raw
        except (TypeError, ValueError):
            return None, None
    if key == 'result':
        text = str(value).strip().lower()
        if text in ('win', '胜利', '胜'):
            return 'win', raw
        if text in ('loss', '失败', '负'):
            return 'loss', raw
        return None, None
    if key == 'mode':
        text = str(value).strip()
        if not text or '未开始匹配' in text:
            return None, None
        return text, raw
    return None, None


def _parse_score(value):
    result = {'left': None, 'right': None}
    if value is None:
        return result
    if isinstance(value, dict):
        for side in ('left', 'right'):
            for key in (side, f'{side}Score', f'{side}_score'):
                number = mimo_ocr.clean_number(value.get(key), 'int')
                if number is not None:
                    result[side] = number
                    break
        return result
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        result['left'] = mimo_ocr.clean_number(value[0], 'int')
        result['right'] = mimo_ocr.clean_number(value[1], 'int')
        return result
    text = str(value)
    match = re.search(r'(\d{1,3})\s*[:\-比]\s*(\d{1,3})', text)
    if match:
        result['left'], result['right'] = int(match.group(1)), int(match.group(2))
    return result


def _merge_player(target, source, page, warnings, stats, entries, hero_names, resolve_name):
    nickname = _clean_text(source.get('nickname'))
    if nickname and not _bad_nickname(nickname, hero_names):
        current = target.get('nickname')
        if current is None:
            target['nickname'] = _field(nickname, nickname)
            stats['nicknames'] += 1
            stats['filled'] += 1
        elif _norm(current.get('value')) == _norm(nickname):
            current['agreement'] = 'mimo'
            stats['agreed'] += 1
        else:
            target['nicknameAlt'] = _field(nickname, nickname)
            warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} 昵称快速识别 '
                            f'{current.get("value")} / Mimo {nickname}')
            stats['conflicts'] += 1

    rating = mimo_ocr.clean_number(source.get('rating'), 'ratio')
    if rating is not None:
        current = target.get('rating')
        if current is None:
            target['rating'] = _field(rating, source.get('rating'))
            stats['filled'] += 1
        elif abs(float(current.get('value')) - rating) > .01:
            warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} 评分快速识别 '
                            f'{current.get("value")} / Mimo {rating}')
            stats['conflicts'] += 1
        else:
            current['agreement'] = 'mimo'
            stats['agreed'] += 1

    title = _clean_text(source.get('title'))
    if title and fast_ocr.TITLE_RE.search(title):
        current = target.get('title')
        if current is None:
            target['title'] = _field(title, title)
            stats['filled'] += 1
        elif current.get('value') != title:
            warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} 称号快速识别 '
                            f'{current.get("value")} / Mimo {title}')
            stats['conflicts'] += 1
        else:
            current['agreement'] = 'mimo'
    if source.get('mvp'):
        target['mvp'] = True

    hero = _clean_text(source.get('hero'))
    if hero:
        exact = hero if hero in hero_names else None
        if exact is None:
            resolved = resolve_name([{'raw': hero, 'confidence': 1.0}], entries)
            candidates = resolved.get('candidates') or []
            _add_candidates(target, candidates, 'mimo-name')
        if exact and target.get('heroSource') != 'manual':
            current = target.get('hero')
            if current is None:
                target['hero'] = _field(exact, hero)
                target['heroStatus'] = 'exact'
                target['heroSource'] = 'mimo'
                stats['heroes'] += 1
                stats['filled'] += 1
            elif current.get('value') == exact:
                target['heroStatus'] = 'exact'
                target['heroSource'] = 'consensus'
                current['agreement'] = 'mimo'
                stats['agreed'] += 1
            elif target.get('heroStatus') in ('auto-matched', 'uncertain', 'unreadable', None):
                target.setdefault('heroAlternatives', []).append(
                    {'value': current.get('value'), 'source': 'rapid'})
                target['hero'] = _field(exact, hero)
                target['heroStatus'] = 'exact'
                target['heroSource'] = 'mimo'
                stats['heroes'] += 1
                stats['conflicts'] += 1
                warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} 英雄由 Mimo '
                                f'修正为 {exact}（快速识别 {current.get("value")}）')
            else:
                target.setdefault('heroAlternatives', []).append(
                    {'value': exact, 'source': 'mimo'})
                warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} 英雄快速识别 '
                                f'{current.get("value")} / Mimo {exact}')
                stats['conflicts'] += 1
        elif exact:
            target.setdefault('heroAlternatives', []).append({'value': exact, 'source': 'mimo'})

    if page in PAGE_FIELDS:
        allowed = set(PAGE_FIELDS[page])
    else:
        allowed = set(CORE_FIELDS) | set(CORE_SHARES) | set(IDENTITY)
    for key, value in source.items():
        if key in IDENTITY or key in ('side', 'slot', 'shares', 'fields'):
            continue
        if key not in PLAYER_FIELDS or key not in FIELD_UNITS or key not in allowed:
            continue
        kind = FIELD_UNITS.get(key)
        parsed = mimo_ocr.clean_number(value, kind)
        if parsed is None:
            continue
        _merge_field(target, 'fields', key, parsed, value, warnings, stats)
    shares = source.get('shares') if isinstance(source.get('shares'), dict) else {}
    for key, value in shares.items():
        if key not in SHARE_FIELDS or key not in allowed:
            continue
        parsed = mimo_ocr.clean_number(value, 'percent')
        if parsed is None:
            continue
        _merge_field(target, 'shares', key, parsed, value, warnings, stats)
    for key in SHARE_FIELDS:
        if key in source and key in allowed:
            parsed = mimo_ocr.clean_number(source[key], 'percent')
            if parsed is not None:
                _merge_field(target, 'shares', key, parsed, source[key], warnings, stats)


def _merge_field(target, group, key, value, raw, warnings, stats):
    fields = target.setdefault(group, {})
    current = fields.get(key)
    if current is None:
        fields[key] = _field(value, raw)
        stats['filled'] += 1
    elif _same_value(current.get('value'), value):
        current['agreement'] = 'mimo'
        stats['agreed'] += 1
    else:
        current.setdefault('alternatives', []).append(
            {'value': value, 'raw': str(raw), 'source': 'mimo'})
        warnings.append(f'{_side_label(target["side"])}{target["slot"] + 1} '
                        f'{postgame_ocr_label(key)} 快速识别 {current.get("value")} / Mimo {value}')
        stats['conflicts'] += 1


def postgame_ocr_label(key):
    from screenshot_schema import PLAYER_LABELS
    return PLAYER_LABELS.get(key, key)


def _field(value, raw):
    return {'value': value, 'raw': str(raw if raw is not None else value),
            'confidence': None, 'source': 'mimo'}


def _same_value(a, b):
    try:
        return abs(float(a) - float(b)) <= .01
    except (TypeError, ValueError):
        return _norm(a) == _norm(b)


def _norm(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def _clean_text(value):
    if value is None:
        return None
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', str(value)).strip()
    return text or None


def _bad_nickname(text, hero_names):
    if len(text) < 2 or len(text) > 24:
        return True
    if text in hero_names or text in ('MVP', '返回队伍', '双方', '对位', '未开始匹配'):
        return True
    if fast_ocr.TITLE_RE.search(text):
        return True
    if re.fullmatch(r'[\d.%/:\-]+', text):
        return True
    return any(symbol in text for symbol in ('+', '(', ')', '（', '）'))


def _add_candidates(player, candidates, source):
    current = player.setdefault('heroCandidates', [])
    seen = {item.get('name') for item in current}
    for candidate in candidates:
        if candidate.get('name') in seen:
            continue
        current.append({**candidate, 'source': source, 'needsReview': True})
        seen.add(candidate.get('name'))


def _side_label(side):
    return '左' if side == 'left' else '右'


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
