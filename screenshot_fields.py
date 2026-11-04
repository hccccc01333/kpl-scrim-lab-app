"""Screenshot field view used for audit and calibration (old two-column UI).

This module does not add OCR capabilities. It flattens whatever `ocr.recognize`
returns into the fields the screenshot source is allowed to provide, and keeps
visible-but-unmapped text (result/mode candidates) separate from confirmed fields.
The current tabbed post-game UI uses :mod:`postgame_ocr` and
:mod:`screenshot_schema` instead.
"""
SCHEMA = 'kpl-screenshot-fields-v1'

FIELD_ORDER = ('hero', 'rating', 'kills', 'deaths', 'assists', 'gold',
               'damage', 'taken', 'participation')
FIELD_LABELS = {
    'hero': '英雄', 'rating': '评分', 'kills': '击杀', 'deaths': '死亡',
    'assists': '助攻', 'gold': '总经济', 'damage': '输出伤害', 'taken': '承受伤害',
    'participation': '参团率',
}
MODE_WORDS = ('排位', '匹配', '快速', '巅峰', '训练', '峡谷', '5v5', '大乱斗')


def _field(player, key):
    value = (player.get('fields') or {}).get(key)
    if not value:
        return None
    return {'value': value.get('value'), 'raw': value.get('raw'),
            'confidence': value.get('confidence'), 'box': value.get('box')}


def _candidate(texts, words):
    for text in texts:
        clean = str(text or '').strip()
        if any(word in clean for word in words):
            return clean
    return None


def flatten_recognition(result, name=None):
    """Return only the fields the screenshot source can provide, plus candidates."""
    meta = result.get('meta') or {}
    texts = [token.get('text') for token in result.get('tokens') or []]
    players = []
    for player in result.get('players') or []:
        fields = {key: _field(player, key) for key in FIELD_ORDER}
        fields = {key: value for key, value in fields.items() if value is not None}
        players.append({'side': player.get('side'), 'slot': player.get('slot'),
                        'fields': fields})
    equipment = []
    for visual in result.get('visuals') or []:
        if visual.get('kind') != 'equipment':
            continue
        equipment.append({'side': visual.get('side'), 'slot': visual.get('slot'),
                          'index': visual.get('index'), 'status': visual.get('status'),
                          'candidates': visual.get('candidates') or []})
    result_text = _candidate(texts, ('胜利', '失败'))
    mode_text = _candidate(texts, MODE_WORDS)
    return {
        'schema': SCHEMA,
        'file': name,
        'pageType': result.get('kind'),
        'ocrVersion': result.get('version'),
        'match': {
            'date': meta.get('date'),
            'durationMinutes': meta.get('duration'),
            'scores': result.get('scores') or {},
            'resultCandidate': ({'value': 'win' if '胜利' in result_text else 'loss',
                                 'raw': result_text} if result_text else None),
            'modeCandidate': ({'value': mode_text, 'raw': mode_text} if mode_text else None),
        },
        'players': players,
        'equipment': equipment,
        'warnings': result.get('warnings') or [],
    }


def render_summary(flat):
    lines = [f"文件：{flat.get('file') or '截图'}",
             f"页面：{flat.get('pageType') or 'unknown'}  OCR：{flat.get('ocrVersion') or '—'}"]
    match = flat.get('match') or {}
    lines.append(f"日期：{match.get('date') or '—'}  时长：{match.get('durationMinutes') or '—'} 分钟  "
                 f"比分：{match.get('scores') or '—'}")
    result = match.get('resultCandidate')
    mode = match.get('modeCandidate')
    lines.append(f"可见候选：胜负 {result['raw'] if result else '—'}  "
                 f"模式 {mode['raw'] if mode else '—'}（未进入固定字段）")
    for player in flat.get('players') or []:
        fields = player.get('fields') or {}
        text = '  '.join(f"{FIELD_LABELS[key]}={fields[key]['value']}"
                         for key in FIELD_ORDER if key in fields)
        lines.append(f"  {player.get('side')} {int(player.get('slot') or 0) + 1}: {text or '无可读字段'}")
    equipment = flat.get('equipment') or []
    named = [item for item in equipment if item.get('status') == 'reference' and item.get('candidates')]
    lines.append(f"装备：{len(named)} 个候选可用 / {len(equipment)} 个区域；其余需人工核对。")
    for warning in flat.get('warnings') or []:
        lines.append(f'注意：{warning}')
    return '\n'.join(lines)
