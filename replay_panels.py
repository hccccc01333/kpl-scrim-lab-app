"""Replay files -> six post-game panels (no game client).

Input is a local ``.abc`` replay (and optionally its ``.ope`` neighbour).  The
replay contributes the ten-player roster, camps, heroes, winner, MVP and the
1251 ten-player ratings.  The final panel numbers (KDA, gold, damage, damage
taken, participation, healing, control, tower damage) come from the Camp
``battledetail`` payload, which is the same data the in-game post-game tabs
show.  Camp detail is looked up by the ``gameSeq`` embedded in the replay file
name; it is never fabricated.

If no Camp detail is available, the six images are still produced, but every
missing panel field stays ``None`` and the image says so.  This keeps the
project's "missing is not zero" rule.

Usage::

    python replay_panels.py data/replays/<match>.abc --ope data/replays/<match>.ope
    python replay_panels.py <match>.abc --camp-detail data/camp_details/1793606215.json
    python replay_panels.py <match>.abc --out data/reports/<match>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import replay_parser
from screenshot_schema import PAGE_FIELDS, PLAYER_LABELS, TABS

SCHEMA = 'kpl-replay-panels-v1'
PAGES = ('kda', 'data', 'output', 'survival', 'farming', 'team')
IDENTITY_FIELDS = {'nickname', 'hero', 'rating', 'title', 'mvp'}
PERCENT_FIELDS = {
    'participation', 'killsShare', 'deathsShare', 'assistsShare',
    'outputShare', 'takenShare', 'goldShare', 'jungleShare', 'csShare',
    'controlShare', 'healingShare', 'towerShare',
}
SHARE_SOURCE = {
    'killsShare': 'kills', 'deathsShare': 'deaths', 'assistsShare': 'assists',
    'outputShare': 'damageDealt', 'takenShare': 'damageTaken',
    'goldShare': 'gold', 'jungleShare': 'jungleGold', 'csShare': 'cs',
    'controlShare': 'control', 'healingShare': 'healing', 'towerShare': 'towerDamage',
}
# Camp battleStats -> screenshot field.  Damage/taken intentionally use the
# "hero" variants: the six post-game tabs display hero damage, not the larger
# total including minions/monsters.  Verified against the 2026-11-02 sample.
CAMP_FIELDS = {
    'kills': 'killCnt',
    'deaths': 'deadCnt',
    'assists': 'assistCnt',
    'gold': 'money',
    'damageDealt': 'totalHeroHurtCnt',
    'damageTaken': 'totalBeheroHurtCnt',
    'participation': 'joinGamePercent',
    'takenPerDeath': 'behurtPerDeath',
    'damageConversion': 'hurtTransRate',
    'jungleGold': 'monsterCoin',
    'cs': 'killSoldier',
    'control': 'ctrlTime',
    'healing': 'healCnt',
    'towerDamage': 'buildingDamage',
    'rating': 'gradeGame',
}
CAMP_RETENTION_NOTE = '营地详情只保留最近一个月；超期对局无法补齐面板字段。'


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_match_key(path: Path) -> dict:
    """Read game identifiers from the client's replay file name.

    ``20261102_161129_870343216_95868_1793606215_<hash>.abc``
      date, time, relaySvr, gameSvr, gameSeq
    """
    match = re.match(
        r'^(?P<date>\d{8})_(?P<time>\d{6})_(?P<relaySvr>-?\d+)_'
        r'(?P<gameSvr>\d+)_(?P<gameSeq>\d+)_', path.name)
    if not match:
        return {}
    parts = match.groupdict()
    return {
        'date': f'{parts["date"][:4]}-{parts["date"][4:6]}-{parts["date"][6:]}',
        'time': f'{parts["time"][:2]}:{parts["time"][2:4]}:{parts["time"][4:]}',
        'relaySvr': parts['relaySvr'],
        'gameSvr': parts['gameSvr'],
        'gameSeq': parts['gameSeq'],
    }


def load_camp_detail(path: str | Path | None = None, game_seq: str | None = None) -> tuple[dict | None, str | None]:
    """Load a cached Camp ``battledetail`` payload.  Never calls the network."""
    candidate = Path(path) if path else None
    if candidate is None and game_seq:
        candidate = Path('data/camp_details') / f'{game_seq}.json'
    if candidate is None or not candidate.is_file():
        return None, None
    try:
        return json.loads(candidate.read_text(encoding='utf-8')), str(candidate)
    except (OSError, ValueError) as error:
        return None, f'营地详情读取失败：{candidate}（{error}）'


def _camp_side(detail: dict, key: str) -> list[dict]:
    data = detail.get('data') or {}
    roles = []
    for role in data.get(key) or []:
        basic = role.get('basicInfo') or {}
        hero = (role.get('battleRecords') or {}).get('usedHero') or {}
        stats = role.get('battleStats') or {}
        roles.append({
            'nickname': basic.get('roleName'),
            'heroId': hero.get('heroId'),
            'hero': hero.get('heroName'),
            'stats': stats,
        })
    return roles


def camp_players(detail: dict | None) -> dict[tuple[str, int], dict]:
    if not detail:
        return {}
    out = {}
    for key, camp in (('blueRoles', 'blue'), ('redRoles', 'red')):
        for role in _camp_side(detail, key):
            hero_id = role.get('heroId')
            if hero_id is None:
                continue
            out[(camp, int(hero_id))] = role
    return out


def _camp_stat(stats: dict, field: str):
    key = CAMP_FIELDS.get(field)
    if not key or key not in stats:
        return None
    value = stats.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace(',', '')
        try:
            value = int(text) if re.fullmatch(r'-?\d+', text) else float(text)
        except ValueError:
            return None
    if field == 'participation':
        number = float(value)
        return round(number * 100, 1) if number <= 1 else round(number, 1)
    return value


def _rating(report: dict) -> dict[int, float]:
    table = report.get('scoreTable') or {}
    return {int(item['entityId']): float(item['score'])
            for item in table.get('players') or [] if item.get('score') is not None}


def _mvp(report: dict) -> tuple[dict[int, str], str | None]:
    mvp = report.get('mvpScore') or {}
    marked = {}
    win = (mvp.get('winMvp') or {}).get('entityId')
    if win is not None:
        marked[int(win)] = 'win'
    for item in mvp.get('loseMvp') or []:
        if item.get('entityId') is not None:
            marked[int(item['entityId'])] = 'lose'
    return marked, mvp.get('winningCamp')


def _replay_players(report: dict) -> list[dict]:
    ratings = _rating(report)
    mvp, _ = _mvp(report)
    players = []
    for block in report.get('blocks') or []:
        camp = 'blue' if block.get('camp') == 1 else 'red' if block.get('camp') == 2 else None
        if camp is None or block.get('position') is None:
            continue
        entity = block.get('entityId')
        players.append({
            'camp': camp,
            'slot': int(block['position']),
            'entityId': entity,
            'nickname': block.get('name'),
            'hero': block.get('heroName'),
            'heroId': block.get('heroId'),
            'bot': bool(block.get('bot')),
            'rating': ratings.get(entity),
            'mvp': mvp.get(entity),
        })
    players.sort(key=lambda item: (item['camp'] != 'blue', item['slot']))
    return players


def _fill_shares(players: list[dict]) -> None:
    for camp in ('blue', 'red'):
        side = [player for player in players if player['camp'] == camp]
        for share_field, source in SHARE_SOURCE.items():
            values = [player['fields'].get(source) for player in side]
            numbers = [value for value in values if value is not None]
            total = sum(float(value) for value in numbers)
            for player, value in zip(side, values):
                if value is None or not numbers or total <= 0:
                    player['fields'][share_field] = None
                else:
                    player['fields'][share_field] = round(float(value) / total * 100, 1)


def _camp_match(report: dict, detail: dict | None) -> dict:
    data = (detail or {}).get('data') or {}
    head = data.get('head') or {}
    battle = data.get('battle') or {}
    blue = data.get('blueTeam') or {}
    red = data.get('redTeam') or {}
    score = None
    if blue.get('killCnt') is not None and red.get('killCnt') is not None:
        score = {'blue': int(blue['killCnt']), 'red': int(red['killCnt'])}
    winner = None
    if blue.get('gameResult') is True:
        winner = 'blue'
    elif red.get('gameResult') is True:
        winner = 'red'
    return {
        'score': score,
        'winner': winner,
        'durationSec': battle.get('usedTime'),
        'mode': battle.get('mapName') or head.get('mapName'),
        'recorderWon': head.get('gameResult'),
    }


def build_bundle(abc_path: Path, ope_path: Path | None = None,
                 camp_detail: dict | None = None,
                 camp_source: str | None = None) -> dict:
    return build_bundle_from_bytes(
        abc_path.read_bytes(),
        ope_path.read_bytes() if ope_path else None,
        abc_path.name,
        ope_path.name if ope_path else None,
        camp_detail, camp_source)


def build_bundle_from_bytes(abc: bytes, ope: bytes | None = None,
                            abc_name: str = 'replay.abc',
                            ope_name: str | None = None,
                            camp_detail: dict | None = None,
                            camp_source: str | None = None) -> dict:
    report = replay_parser.inspect_replay(abc, ope)
    if not report.get('blocks'):
        raise ValueError('回放里没有读出十人名单；该版本可能未配置解析档案。')

    key = parse_match_key(Path(abc_name))
    camp = camp_players(camp_detail)
    camp_info = _camp_match(report, camp_detail)
    replay_players = _replay_players(report)
    warnings: list[str] = []

    players = []
    for replay in replay_players:
        role = camp.get((replay['camp'], int(replay['heroId']))) if replay.get('heroId') is not None else None
        stats = (role or {}).get('stats') or {}
        fields = {name: _camp_stat(stats, name) for name in CAMP_FIELDS if name != 'rating'}
        camp_rating = _camp_stat(stats, 'rating')
        rating = replay.get('rating')
        if rating is None and camp_rating is not None:
            rating = camp_rating
        elif rating is not None and camp_rating is not None and abs(float(rating) - float(camp_rating)) > 0.05:
            warnings.append(
                f"{replay['nickname'] or replay['hero']} 的评分不一致："
                f"回放 {rating} / 营地 {camp_rating}；保留回放值并并列营地值。")
        fields['rating'] = rating
        if camp_rating is not None:
            fields['campRating'] = camp_rating
        fields['mvp'] = replay.get('mvp') or ('win' if stats.get('mvp') else None)
        # 称号（金牌/银牌…）在 Camp battleStats 里没有与截图逐字对齐的字段，
        # 先留空，避免把 evaluateIcon 的分级猜成称号。
        fields['title'] = None
        if not stats:
            warnings.append(f"{replay['nickname'] or replay['hero']} 没有营地十人面板，KDA/经济等留空。")
        players.append({
            'camp': replay['camp'],
            'slot': replay['slot'],
            'entityId': replay['entityId'],
            'nickname': replay['nickname'],
            'hero': replay['hero'],
            'heroId': replay['heroId'],
            'bot': replay['bot'],
            'fields': fields,
            'sources': {
                'identity': 'replay',
                'rating': 'replay' if replay.get('rating') is not None else ('camp' if camp_rating is not None else None),
                'stats': 'camp' if stats else None,
            },
        })

    _fill_shares(players)

    mvp, replay_winner = _mvp(report)
    winning_camp = replay_winner or camp_info.get('winner')
    if replay_winner and camp_info.get('winner') and replay_winner != camp_info['winner']:
        warnings.append(
            f'胜负来源冲突：回放判 {replay_winner} 胜，营地判 {camp_info["winner"]} 胜；'
            '保留回放值并列出营地值。')
    recorder_camp = next(
        (('blue' if block.get('camp') == 1 else 'red')
         for block in report.get('blocks') or [] if block.get('self')), None)
    recorder_won = camp_info.get('recorderWon')
    if recorder_won is None and recorder_camp and winning_camp:
        recorder_won = recorder_camp == winning_camp
    result = 'win' if recorder_won is True else 'loss' if recorder_won is False else None
    if camp_info.get('score'):
        blue_score = camp_info['score']['blue']
        red_score = camp_info['score']['red']
    else:
        blue_score = red_score = None
    duration = camp_info.get('durationSec')
    duration_source = 'camp' if duration is not None else None
    if duration is None:
        total_frames = report['header'].get('totalFrameNum')
        if total_frames:
            duration = round(total_frames / 15)
            duration_source = 'replay-frames/15'
            warnings.append('未取到营地时长；时长由回放帧数 / 15 估算，标为 partial。')

    match = {
        'gameSeq': key.get('gameSeq'),
        'gameSvr': key.get('gameSvr'),
        'relaySvr': key.get('relaySvr'),
        'date': key.get('date'),
        'time': key.get('time'),
        'durationSec': duration,
        'durationSource': duration_source,
        'mode': camp_info.get('mode'),
        'score': {'blue': blue_score, 'red': red_score},
        'winningCamp': winning_camp,
        'result': result,
        'recorderWon': recorder_won,
        'versions': report['header'].get('versions'),
        'builds': report['header'].get('builds'),
        'totalFrameNum': report['header'].get('totalFrameNum'),
        'mvp': report.get('mvpScore') or None,
    }

    panels = {}
    for page in PAGES:
        columns = [field for field in PAGE_FIELDS[page] if field not in IDENTITY_FIELDS]
        panels[page] = {
            'label': TABS.get(page, page),
            'fields': columns,
            'rows': [{
                'camp': player['camp'],
                'slot': player['slot'],
                'nickname': player['nickname'],
                'hero': player['hero'],
                'rating': player['fields'].get('rating'),
                'mvp': player['fields'].get('mvp'),
                'title': player['fields'].get('title'),
                'values': {field: player['fields'].get(field) for field in columns},
            } for player in players],
        }

    if camp_detail is None:
        warnings.append('没有营地面板：六页仍会生成，但 KDA/经济/输出/承伤/参团等字段为空。' + CAMP_RETENTION_NOTE)
    return {
        'schema': SCHEMA,
        'match': match,
        'players': players,
        'panels': panels,
        'warnings': warnings,
        'provenance': {
            'abc': abc_name,
            'ope': ope_name,
            'abcSha256': _sha256(abc),
            'opeSha256': _sha256(ope) if ope else None,
            'campDetail': camp_source,
            'parserVersion': report.get('parserVersion'),
            'panelSource': 'camp-battledetail' if camp_detail else None,
        },
    }


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = (
        ('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc'),
        'C:/Windows/Fonts/simhei.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw, xy, value, font, fill):
    draw.text(xy, '' if value is None else str(value), font=font, fill=fill)


def _format(field: str, value):
    if value is None:
        return '—'
    if field in PERCENT_FIELDS:
        number = float(value)
        return f'{number:.1f}%' if abs(number - round(number)) >= 0.05 else f'{round(number)}%'
    if field == 'damageConversion':
        return f'{float(value):.2f}'.rstrip('0').rstrip('.')
    if field == 'rating':
        return f'{float(value):.1f}'
    try:
        return f'{int(round(float(value))):,}'
    except (TypeError, ValueError):
        return str(value)


def _fit(draw, value, font, width: float) -> str:
    text = '' if value is None else str(value)
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text + '…'


def render_page(bundle: dict, page: str, out_path: Path) -> Path:
    from PIL import Image, ImageDraw
    width, height = 1920, 1080
    image = Image.new('RGB', (width, height), (12, 20, 32))
    draw = ImageDraw.Draw(image)
    match = bundle['match']
    panel = bundle['panels'][page]
    score = match.get('score') or {}
    blue_score = score.get('blue')
    red_score = score.get('red')
    result = '胜方 蓝' if match.get('winningCamp') == 'blue' else '胜方 红' if match.get('winningCamp') == 'red' else '胜负 —'

    _text(draw, (48, 32), 'KPL 赛训 · 回放结算', _font(30, True), (226, 235, 245))
    _text(draw, (48, 78), f'{match.get("date") or "日期 —"}  {match.get("time") or ""}  '
                         f'时长 {_duration(match.get("durationSec"))}  {match.get("mode") or "模式 —"}',
          _font(18), (148, 168, 190))
    _text(draw, (width - 430, 38), f'{blue_score if blue_score is not None else "—"}  :  '
                                   f'{red_score if red_score is not None else "—"}',
          _font(44, True), (232, 238, 248))
    _text(draw, (width - 300, 94), result, _font(20, True), (120, 205, 170))
    _text(draw, (48, 132), panel['label'], _font(44, True), (240, 214, 128))
    _text(draw, (190, 150), f'第 {PAGES.index(page) + 1} / {len(PAGES)} 页', _font(17), (120, 140, 165))

    warning = '营地面板不可用：本页只含回放名单与评分，KDA / 经济 / 输出 / 承伤 / 参团留空。' \
        if bundle['provenance'].get('panelSource') is None else None
    if warning:
        draw.rectangle([48, 192, width - 48, 232], fill=(80, 45, 34))
        _text(draw, (64, 201), warning, _font(18, True), (255, 196, 120))

    left, right = 48, width - 48
    fixed = (('阵营', 76), ('选手', 220), ('英雄', 140), ('评分', 88))
    columns = panel['fields']
    table_w = right - left
    fixed_w = sum(item[1] for item in fixed)
    col_w = (table_w - fixed_w) / max(1, len(columns))
    header_y = 252
    draw.rounded_rectangle([left, header_y, right, header_y + 38], radius=8, fill=(22, 34, 50))
    x = left + 14
    for label, cell_w in fixed:
        _text(draw, (x, header_y + 9), label, _font(15, True), (140, 158, 180))
        x += cell_w
    for field in columns:
        _text(draw, (x + 4, header_y + 9), PLAYER_LABELS.get(field, field),
              _font(14, True), (140, 158, 180))
        x += col_w

    rows = sorted(panel['rows'], key=lambda row: (row['camp'] != 'blue', row['slot']))
    row_h = 68
    row_top = header_y + 44
    for index, row in enumerate(rows):
        top = row_top + index * row_h
        blue = row['camp'] == 'blue'
        accent = (64, 148, 214) if blue else (216, 92, 108)
        fill = ((18, 34, 52) if blue else (44, 25, 34)) if index % 2 == 0 else \
               ((16, 30, 46) if blue else (38, 22, 30))
        draw.rounded_rectangle([left, top, right, top + row_h - 5], radius=8, fill=fill)
        draw.rectangle([left, top, left + 6, top + row_h - 5], fill=accent)
        x = left + 14
        _text(draw, (x, top + 23), '蓝' if blue else '红', _font(18, True), accent)
        x += 76
        name_font = _font(20, True)
        _text(draw, (x, top + 7), _fit(draw, row.get('nickname') or row.get('hero'), name_font, 200),
              name_font, (232, 238, 248))
        badge = 'MVP' if row.get('mvp') == 'win' else '败方MVP' if row.get('mvp') == 'lose' \
            else (row.get('title') or '')
        if badge:
            _text(draw, (x, top + 37), badge, _font(13, True), (240, 196, 96))
        x += 220
        _text(draw, (x, top + 23), _fit(draw, row.get('hero'), _font(17), 122),
              _font(17), (168, 186, 208))
        x += 140
        rating = row.get('rating')
        color = (240, 196, 96) if rating is not None and float(rating) >= 10 else (220, 228, 238)
        _text(draw, (x, top + 17), _format('rating', rating), _font(26, True), color)
        x += 88
        for field in columns:
            value = row.get('values', {}).get(field)
            color = (120, 130, 145) if value is None else (214, 224, 236)
            _text(draw, (x + 4, top + 20), _format(field, value), _font(19, True), color)
            x += col_w

    footer = (f'平台生成，不是游戏原图。数据来源：回放文件（名单 / 胜负 / MVP / 评分）'
              f'{" + 营地十人面板" if bundle["provenance"].get("panelSource") else ""}'
              f'；gameSeq {match.get("gameSeq") or "—"}。缺失字段显示 —。')
    _text(draw, (48, height - 54), footer, _font(16), (110, 128, 150))
    _text(draw, (48, height - 30), f'回放 {bundle["provenance"].get("abc") or "—"}',
          _font(14), (86, 102, 122))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def _duration(value) -> str:
    if value is None:
        return '—'
    seconds = max(0, int(round(float(value))))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def write_bundle(bundle: dict, out_dir: str | Path, images: bool = True) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'panels.json').write_text(
        json.dumps(bundle, ensure_ascii=False, indent=1), encoding='utf-8')
    files = {}
    if images:
        for index, page in enumerate(PAGES, 1):
            name = f'{index:02d}-{bundle["panels"][page]["label"]}.png'
            files[page] = str(render_page(bundle, page, out / name))
    return {'json': str(out / 'panels.json'), 'images': files}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('abc', type=Path)
    parser.add_argument('--ope', type=Path)
    parser.add_argument('--camp-detail', type=Path,
                        help='cached Camp battledetail JSON (default: data/camp_details/<gameSeq>.json)')
    parser.add_argument('--out', type=Path, help='output directory (default: data/reports/replay-panels/<stem>)')
    parser.add_argument('--no-images', action='store_true', help='write panels.json only')
    args = parser.parse_args(argv)
    if not args.abc.is_file():
        parser.error(f'找不到回放文件：{args.abc}')
    key = parse_match_key(args.abc)
    detail, detail_source = load_camp_detail(args.camp_detail, key.get('gameSeq'))
    bundle = build_bundle(args.abc, args.ope, detail, detail_source)
    out = args.out or (Path('data/reports/replay-panels') / args.abc.stem)
    written = write_bundle(bundle, out, images=not args.no_images)
    print(json.dumps({
        'schema': bundle['schema'],
        'match': {k: bundle['match'].get(k) for k in ('gameSeq', 'date', 'durationSec', 'score', 'winningCamp')},
        'players': len(bundle['players']),
        'warnings': bundle['warnings'],
        'output': written,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
