"""赛训组自定义「分路 × 字段」评级规则。

口径（2026-11-21）：
- 赛训组在设置页为每个评分主体（分路；打野再分坦野/野核）的每个字段设定
  4 档阈值：卓越 / 优秀 / 达标 / 待提升。规则优先级最高，保存后所有评级按这里取数；
  没保存过时用内置默认（仅展示/兜底，不参与分析口径）。
- 数据落在 data/facts/grade_rules.json，尊重 KPL_DATA_DIR 覆盖（与 combo_pool 同目录）。
- 字段按**真实口径**，不强行分均：控制时长按秒、经济转治疗按比值、对位经济差按金、
  参团率按 %、死亡按次；只有 gpm/dpm/tpm 本来就是分均。单位写在规则里，界面照实显示。

方向 direction: 'up' = 越高越好，'down' = 越低越好。
阈值 thresholds 为 [卓越线, 优秀线, 达标线]：
  up   : value >= t[0] 卓越; >=t[1] 优秀; >=t[2] 达标; 否则 待提升
  down : value <= t[0] 卓越; <=t[1] 优秀; <=t[2] 达标; 否则 待提升

字段来源 source:
  'player'  → 直接取 player 基础字段（含 gpm/dpm/tpm 现算）
  'tile'    → 取 player.campTiles[] 里 key 对应的 value（营地自适应卡片，可能缺）
  key 为取值键。

主体 key：5 个分路用中文路名；打野的坦野/野核用 '打野·坦野' / '打野·野核'。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import bp_facts

SCHEMA = 'grade-rules-v1'
FILENAME = 'grade_rules.json'
LEVELS = [('elite', '卓越'), ('good', '优秀'), ('pass', '达标'), ('low', '待提升')]

# 字段字典：label/unit/direction/source/key 是契约（前端据此取值与显示）。
# direction 严格照数据来源含义；营地卡片没有公开基准，默认阈值只是占位参考，需赛训组校准。
FIELDS = {
    # ── player 基础字段 ────────────────────────────────────────────────
    'gpm': {'label': '分均经济', 'unit': '金/分', 'direction': 'up', 'source': 'player', 'key': 'gpm'},
    'dpm': {'label': '分均输出', 'unit': '伤害/分', 'direction': 'up', 'source': 'player', 'key': 'dpm'},
    'tpm': {'label': '分均承伤', 'unit': '伤害/分', 'direction': 'down', 'source': 'player', 'key': 'tpm'},
    'gold': {'label': '总经济', 'unit': '金', 'direction': 'up', 'source': 'player', 'key': 'gold'},
    'damage': {'label': '总输出', 'unit': '伤害', 'direction': 'up', 'source': 'player', 'key': 'damage'},
    'taken': {'label': '总承伤', 'unit': '伤害', 'direction': 'down', 'source': 'player', 'key': 'taken'},
    'participation': {'label': '参团率', 'unit': '%', 'direction': 'up', 'source': 'player', 'key': 'participation'},
    'kills': {'label': '击杀数', 'unit': '次', 'direction': 'up', 'source': 'player', 'key': 'kills'},
    'deaths': {'label': '死亡数', 'unit': '次', 'direction': 'down', 'source': 'player', 'key': 'deaths'},
    'assists': {'label': '助攻数', 'unit': '次', 'direction': 'up', 'source': 'player', 'key': 'assists'},
    'damageConversion': {'label': '伤害转化率', 'unit': '比值', 'direction': 'up', 'source': 'player', 'key': 'damageConversion'},
    'takenPerDeath': {'label': '每死承伤', 'unit': '伤害/次', 'direction': 'down', 'source': 'player', 'key': 'takenPerDeath'},
    'cs': {'label': '补兵数', 'unit': '个', 'direction': 'up', 'source': 'player', 'key': 'cs'},
    'towerDamage': {'label': '对塔伤害', 'unit': '伤害', 'direction': 'up', 'source': 'player', 'key': 'towerDamage'},
    'jungleGold': {'label': '野怪经济', 'unit': '金', 'direction': 'up', 'source': 'player', 'key': 'jungleGold'},
    # ── 营地自适应卡片（campTiles）────────────────────────────────────
    'vision': {'label': '视野价值', 'unit': '值', 'direction': 'up', 'source': 'tile', 'key': 'vision'},
    'control_time': {'label': '控制时长', 'unit': '秒', 'direction': 'up', 'source': 'tile', 'key': 'control_time'},
    'hard_control_time': {'label': '硬控时长', 'unit': '秒', 'direction': 'up', 'source': 'tile', 'key': 'hard_control_time'},
    'gold_to_heal': {'label': '经济转治疗', 'unit': '比值', 'direction': 'up', 'source': 'tile', 'key': 'gold_to_heal'},
    'gold_to_taken': {'label': '经济转有效承伤', 'unit': '比值', 'direction': 'up', 'source': 'tile', 'key': 'gold_to_taken'},
    'effective_taken': {'label': '有效承伤', 'unit': '%', 'direction': 'down', 'source': 'tile', 'key': 'effective_taken'},
    'effective_damage': {'label': '有效伤害', 'unit': '%', 'direction': 'up', 'source': 'tile', 'key': 'effective_damage'},
    'gold_to_damage': {'label': '经济转有效伤害', 'unit': '比值', 'direction': 'up', 'source': 'tile', 'key': 'gold_to_damage'},
    'lane_gold_diff': {'label': '对位经济差', 'unit': '金', 'direction': 'up', 'source': 'tile', 'key': 'lane_gold_diff'},
    'lane_gold_diff_early': {'label': '对线期对位经济差', 'unit': '金', 'direction': 'up', 'source': 'tile', 'key': 'lane_gold_diff_early'},
    'lane_resource_diff': {'label': '对位资源差', 'unit': '金', 'direction': 'up', 'source': 'tile', 'key': 'lane_resource_diff'},
    'side_lane_gold': {'label': '带线总经济', 'unit': '金', 'direction': 'up', 'source': 'tile', 'key': 'side_lane_gold'},
    'solo_kill': {'label': '全局单杀次数', 'unit': '次', 'direction': 'up', 'source': 'tile', 'key': 'solo_kill'},
    'dragon_participation': {'label': '参与控龙次数', 'unit': '次', 'direction': 'up', 'source': 'tile', 'key': 'dragon_participation'},
    'invade_gold': {'label': '反野总经济', 'unit': '金', 'direction': 'up', 'source': 'tile', 'key': 'invade_gold'},
    'key_assist': {'label': '关键助攻', 'unit': '次', 'direction': 'up', 'source': 'tile', 'key': 'key_assist'},
}

SUBJECT_LABELS = {
    '对抗路': '对抗路', '发育路': '发育路', '中路': '中路',
    '打野·坦野': '打野·坦野', '打野·野核': '打野·野核', '游走': '游走（辅助）',
}

# 每个分路默认要看的字段（来自 campTiles 的 roles 标注 + 基础字段的教练口径）。
# 阈值：基础字段用常见赛训值；营地卡片字段无公开基准，给占位参考值并在 note 标注需校准。
_DEFAULT_SUBJECTS = {
    '对抗路': {
        'gpm': [740, 700, 680], 'lane_gold_diff': [1500, 800, 300],
        'lane_gold_diff_early': [600, 300, 0], 'solo_kill': [2, 1, 1],
        'effective_taken': [40, 55, 70], 'participation': [70, 60, 50],
        'deaths': [2, 3, 4], 'tpm': [800, 1000, 1200],
    },
    '发育路': {
        'gpm': [740, 700, 680], 'lane_gold_diff': [1500, 800, 300],
        'gold_to_damage': [7, 6, 5], 'dpm': [950, 800, 650],
        'participation': [70, 60, 50], 'deaths': [2, 3, 4], 'tpm': [700, 900, 1100],
    },
    '中路': {
        'gpm': [600, 575, 550], 'gold_to_damage': [7, 6, 5],
        'dpm': [850, 700, 550], 'participation': [78, 68, 58], 'deaths': [2, 3, 4],
    },
    '打野·坦野': {
        'gpm': [740, 710, 680], 'dragon_participation': [4, 3, 2],
        'invade_gold': [3000, 2000, 1000], 'participation': [80, 70, 60],
        'deaths': [2, 3, 4], 'tpm': [1000, 1200, 1400],
    },
    '打野·野核': {
        'gpm': [860, 820, 800], 'dragon_participation': [3, 2, 1],
        'invade_gold': [2500, 1500, 800], 'solo_kill': [2, 1, 1],
        'dpm': [900, 750, 600], 'participation': [72, 62, 52], 'deaths': [2, 3, 4],
    },
    '游走': {
        'control_time': [30, 20, 12], 'vision': [80, 60, 40],
        'gold_to_heal': [8, 6, 4], 'effective_taken': [40, 55, 70],
        'participation': [80, 70, 60], 'deaths': [2, 3, 4],
    },
}


def _rule(field: str, thresholds: list) -> dict:
    meta = FIELDS[field]
    return {
        'label': meta['label'], 'unit': meta['unit'], 'direction': meta['direction'],
        'source': meta['source'], 'key': meta['key'],
        'thresholds': list(thresholds),
        'estimate': meta['source'] == 'tile',   # 营地卡片字段：阈值是占位参考值
    }


def path() -> Path:
    return bp_facts.FACTS / FILENAME


def _default_doc() -> dict:
    return {
        'schema': SCHEMA,
        'revision': 0,
        'updatedAt': '',
        'subjects': {
            subject: {field: _rule(field, thresholds) for field, thresholds in fields.items()}
            for subject, fields in _DEFAULT_SUBJECTS.items()
        },
    }


def _valid(doc: object) -> bool:
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        return False
    subjects = doc.get('subjects')
    if not isinstance(subjects, dict) or not subjects:
        return False
    for subject, fields in subjects.items():
        if not isinstance(subject, str) or not isinstance(fields, dict):
            return False
        for field, rule in fields.items():
            if not isinstance(field, str) or not isinstance(rule, dict):
                return False
            if rule.get('direction') not in ('up', 'down'):
                return False
            thresholds = rule.get('thresholds')
            if not isinstance(thresholds, list) or len(thresholds) != 3:
                return False
            if not all(isinstance(x, (int, float)) for x in thresholds):
                return False
    return True


def read_saved() -> dict | None:
    file = path()
    if not file.exists():
        return None
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        return doc if _valid(doc) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    return read_saved() or _default_doc()


def save(doc: dict, bump: bool = True, summary: str = '') -> dict:
    if not _valid(doc):
        raise ValueError('评级规则数据格式不正确')
    import config_history
    config_history.record('grade_rules', read_saved(), doc,
                          summary or config_history.diff_summary('grade_rules', read_saved(), doc))
    out = {
        'schema': SCHEMA,
        'revision': int(doc.get('revision') or 0) + (1 if bump else 0),
        'updatedAt': doc.get('updatedAt') or '',
        'subjects': doc['subjects'],
    }
    if not out['updatedAt']:
        from datetime import datetime, timezone
        out['updatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='grade_rules-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(out, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out


def has_saved() -> bool:
    return read_saved() is not None


def field_value(player: dict, rule: dict) -> float | None:
    """按规则的 source/key 从选手对象取真实值；取不到返回 None（该局没这张卡）。"""
    if not isinstance(player, dict) or not isinstance(rule, dict):
        return None
    key = rule.get('key') or ''
    source = rule.get('source')
    if source == 'tile':
        for tile in player.get('campTiles') or []:
            if isinstance(tile, dict) and tile.get('key') == key:
                value = tile.get('value')
                return float(value) if isinstance(value, (int, float)) else None
        return None
    # player 基础字段：gpm/dpm/tpm 未落盘时按 duration 现算
    value = player.get(key) if key in ('gpm', 'dpm', 'tpm') else player.get(key)
    if value is None and key in ('gpm', 'dpm', 'tpm'):
        minutes = float(player.get('minutes') or 0)
        base = {'gpm': 'gold', 'dpm': 'damage', 'tpm': 'taken'}[key]
        if minutes > 0 and player.get(base) is not None:
            value = float(player[base]) / minutes
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def grade(subject: str, field: str, value, doc: dict | None = None):
    """按规则给一个数值定档。返回 {'level','label'} 或 None。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    rules = (doc or read_saved() or {}).get('subjects') or {}
    rule = rules.get(subject, {}).get(field)
    if not rule:
        return None
    thresholds = rule['thresholds']
    down = rule['direction'] == 'down'
    level = 'low'
    if (number <= thresholds[0] if down else number >= thresholds[0]):
        level = 'elite'
    elif (number <= thresholds[1] if down else number >= thresholds[1]):
        level = 'good'
    elif (number <= thresholds[2] if down else number >= thresholds[2]):
        level = 'pass'
    return {'level': level, 'label': dict(LEVELS)[level]}


def subject_for(position, hero=None, player=None) -> str:
    pos = str(position or '').strip()
    if pos == '打野':
        blade = player.get('blade') if isinstance(player, dict) else None
        kind = blade.get('kind') if isinstance(blade, dict) else None
        return '打野·坦野' if kind == 'tank' else '打野·野核'
    return pos if pos in SUBJECT_LABELS else ''
