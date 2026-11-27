"""赛训组自定义「分路 × 字段」评级规则。

口径（2026-11-21；2026-11-24 补「全字段 + 生效勾选」）：
- 赛训组在设置页为每个评分主体（分路；打野再分坦野/野核）设定 4 档阈值：
  卓越 / 优秀 / 达标 / 待提升。规则优先级最高，保存后所有评级按这里取数；
  没保存过时用内置默认（仅展示/兜底，不参与分析口径）。
- 设置页**列全 FIELDS 里的所有字段**（不再只列每路默认那几个），每行带 active
  勾选：勾上才进入评级口径；没勾的字段即使有阈值也不参与计算/展示。
- 老存档缺字段或缺 active 时，load() 会自动补齐（新增字段默认不生效，老字段
  默认生效），赛训组点一次保存即整体落盘。
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
    'cs': {'label': '补兵数', 'unit': '个', 'direction': 'up', 'source': 'player', 'key': 'cs',
           'minuteSubjects': ['发育路', '对抗路', '中路']},
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

# 补刀是「按局时长匹配」的特殊指标：分钟 → 标准补刀数。
# 初值来自赛训组下发的分路表；规则设置里可继续加 21/22/23… 分钟。
CS_MINUTE_STANDARDS = {
    '发育路': {1: 3, 2: 6, 3: 18, 4: 27, 5: 36, 6: 42, 7: 45, 8: 48, 9: 51, 10: 54,
               11: 59, 12: 64, 13: 69, 14: 75, 15: 80, 16: 85, 17: 91, 18: 96, 19: 101, 20: 108},
    '对抗路': {1: 3, 2: 6, 3: 18, 4: 27, 5: 36, 6: 42, 7: 45, 8: 48, 9: 51, 10: 54,
               11: 59, 12: 64, 13: 69, 14: 75, 15: 80, 16: 85, 17: 91, 18: 96, 19: 101, 20: 108},
    '中路': {1: 4, 2: 8, 3: 12, 4: 28, 5: 31, 6: 34, 7: 37, 8: 40, 9: 43, 10: 46,
             11: 55, 12: 64, 13: 73, 14: 82, 15: 91, 16: 100, 17: 109, 18: 112, 19: 115, 20: 115},
}
CS_MINUTE_FLOOR = 18  # 局时长不足 19 分钟时统一按 18 分钟标准，避免早停局被误判

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


# 全字段兜底阈值：优先取现有分路默认里第一个出现值；没出现过的基础字段给一个
# 粗略占位（勾选后赛训组按实战改）。这些字段默认 active=False。
_SUGGESTED_THRESHOLDS = {
    'gold': [12000, 9000, 6000], 'damage': [80000, 60000, 40000],
    'taken': [90000, 130000, 180000], 'kills': [6, 4, 2],
    'assists': [10, 7, 4], 'damageConversion': [1.2, 0.9, 0.6],
    'takenPerDeath': [20000, 30000, 45000], 'cs': [250, 180, 120],
    'towerDamage': [12000, 8000, 4000], 'jungleGold': [9000, 6500, 4000],
    'hard_control_time': [20, 12, 6], 'gold_to_taken': [1.2, 0.9, 0.6],
    'effective_damage': [30, 22, 15], 'lane_resource_diff': [800, 400, 0],
    'side_lane_gold': [6000, 4000, 2000], 'key_assist': [6, 4, 2],
}
_FALLBACK_THRESHOLDS = dict(_SUGGESTED_THRESHOLDS)
for _fields in _DEFAULT_SUBJECTS.values():
    for _field, _thresholds in _fields.items():
        _FALLBACK_THRESHOLDS.setdefault(_field, _thresholds)


def _clean_minute_standard(value, fallback: dict | None = None) -> dict:
    """补刀分钟表：键是分钟（字符串），值是标准补刀数；非法值退回默认表。"""
    source = value if isinstance(value, dict) else (fallback or {})
    out = {}
    for minute, count in source.items():
        try:
            key = int(str(minute).strip())
            val = int(count)
        except (TypeError, ValueError):
            continue
        if 1 <= key <= 240 and val >= 0:
            out[str(key)] = val
    if out:
        return dict(sorted(out.items(), key=lambda item: int(item[0])))
    return {str(k): int(v) for k, v in (fallback or {}).items()}


def _rule(field: str, thresholds: list, active: bool = False, subject: str = '') -> dict:
    meta = FIELDS[field]
    rule = {
        'label': meta['label'], 'unit': meta['unit'], 'direction': meta['direction'],
        'source': meta['source'], 'key': meta['key'],
        'thresholds': list(thresholds),
        'estimate': meta['source'] == 'tile',   # 营地卡片字段：阈值是占位参考值
        'active': bool(active),                 # 勾上才进入评级口径
    }
    if field == 'cs' and subject in CS_MINUTE_STANDARDS:
        rule['minuteStandard'] = _clean_minute_standard(None, CS_MINUTE_STANDARDS[subject])
    return rule


def path() -> Path:
    return bp_facts.FACTS / FILENAME


def _default_doc() -> dict:
    """每个主体列全 FIELDS；只有该分路原本配过的字段默认勾选生效。"""
    subjects = {}
    for subject in SUBJECT_LABELS:
        configured = _DEFAULT_SUBJECTS.get(subject) or {}
        subjects[subject] = {
            field: _rule(field, configured.get(field) or _FALLBACK_THRESHOLDS.get(field, [0, 0, 0]),
                         active=field in configured, subject=subject)
            for field in FIELDS
        }
    return {
        'schema': SCHEMA,
        'revision': 0,
        'updatedAt': '',
        'subjects': subjects,
    }


def normalize(doc: dict | None) -> dict:
    """把任意版本存档补齐成「全字段 + active」结构，供展示与评级共用。

    已保存的字段优先：阈值 / 标签等原样保留，active 缺省时按内置默认判定；
    存档里没有的字段用内置默认补上并标为不生效（赛训组可再勾）。
    """
    base = _default_doc()
    if not isinstance(doc, dict) or not isinstance(doc.get('subjects'), dict):
        return base
    saved = doc['subjects']
    subjects = {}
    for subject in SUBJECT_LABELS:
        incoming = saved.get(subject) if isinstance(saved.get(subject), dict) else {}
        fields = {}
        for field, rule in base['subjects'][subject].items():
            old = incoming.get(field)
            if isinstance(old, dict) and isinstance(old.get('thresholds'), list) \
                    and len(old['thresholds']) == 3 \
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                            for x in old['thresholds']) \
                    and old.get('direction') in ('up', 'down'):
                merged = dict(rule)
                merged.update(old)
                merged['active'] = bool(old.get('active', rule['active']))
                if 'minuteStandard' in rule:
                    merged['minuteStandard'] = _clean_minute_standard(
                        old.get('minuteStandard'), rule['minuteStandard'])
                fields[field] = merged
            else:
                fields[field] = rule
        subjects[subject] = fields
    return {**doc, 'schema': SCHEMA, 'subjects': subjects}


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
            minutes = rule.get('minuteStandard')
            if minutes is not None:
                if not isinstance(minutes, dict) or not minutes:
                    return False
                for key, val in minutes.items():
                    try:
                        minute = int(str(key).strip())
                        count = int(val)
                    except (TypeError, ValueError):
                        return False
                    if not (1 <= minute <= 240 and count >= 0 and not isinstance(val, bool)):
                        return False
            thresholds = rule.get('thresholds')
            if not isinstance(thresholds, list) or len(thresholds) != 3:
                return False
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                       for x in thresholds):
                return False
            if 'active' in rule and not isinstance(rule['active'], bool):
                return False
            # 阈值必须和 direction 同向：up 是 elite≥good≥pass，down 是 elite≤good≤pass。
            # 倒序阈值会让 grade() 把「差」判成「卓越」，且保存时以前不报错。
            if rule['direction'] == 'down':
                if not (thresholds[0] <= thresholds[1] <= thresholds[2]):
                    return False
            elif not (thresholds[0] >= thresholds[1] >= thresholds[2]):
                return False
    return True


def read_saved() -> dict | None:
    file = path()
    if not file.exists():
        return None
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        return normalize(doc) if _valid(doc) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    return read_saved() or _default_doc()


def save(doc: dict, bump: bool = True, summary: str = '') -> dict:
    if not _valid(doc):
        raise ValueError('评级规则数据格式不正确')
    doc = normalize(doc)   # 老存档/旧客户端提交时补齐全字段与 active，整体落盘
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


def _minute_standard_key(table: dict, minutes) -> str | None:
    """按局时长挑补刀标准档：<19 分钟按 18 分钟；未配置的分钟向下取最近档。"""
    keys = sorted((int(k) for k in table), key=int)
    if not keys:
        return None
    try:
        minute = int(round(float(minutes)))
    except (TypeError, ValueError):
        return None
    if minute < CS_MINUTE_FLOOR:
        minute = CS_MINUTE_FLOOR
    lower = [k for k in keys if k <= minute]
    return str(lower[-1] if lower else keys[0])


def grade(subject: str, field: str, value, doc: dict | None = None, minutes=None):
    """按规则给一个数值定档。返回 {'level','label'} 或 None。

    `minutes` 只供按局时长匹配的字段（目前是补刀 cs）使用。
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    source = doc if doc is not None else read_saved()
    if not source or not source.get('subjects') or source.get('saved') is False:
        return None        # 未保存时不拿内置默认参与评级口径
    rules = normalize(source).get('subjects') or {}
    rule = rules.get(subject, {}).get(field)
    if not rule or not rule.get('active', True):
        return None        # 没勾选生效的字段不进入任何评级口径
    minute_table = rule.get('minuteStandard') if field == 'cs' else None
    if isinstance(minute_table, dict) and minute_table:
        key = _minute_standard_key(minute_table, minutes)
        if key is None:
            return None
        # 赛训口径：中路补刀只作蓝色参考，不按标准分金红；发育/对抗按分钟标准定档。
        if subject == '中路':
            return {'level': 'ok', 'label': '达标'}
        standard = float(minute_table[key])
        if number > standard:
            return {'level': 'elite', 'label': '高于标准'}
        if number < standard:
            return {'level': 'low', 'label': '低于标准'}
        return {'level': 'ok', 'label': '达标'}
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


_HERO_LANE_TYPES_CACHE = None


def _hero_lane_types() -> dict:
    """英雄 × 实际分路 → 分类，来自 resources/hero_tags.json（只读、懒加载）。"""
    global _HERO_LANE_TYPES_CACHE
    if _HERO_LANE_TYPES_CACHE is not None:
        return _HERO_LANE_TYPES_CACHE
    path = Path(__file__).resolve().parent / 'resources' / 'hero_tags.json'
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        _HERO_LANE_TYPES_CACHE = {
            str(name): (value.get('lanes') or {})
            for name, value in (raw.get('heroes') or {}).items()
            if isinstance(value, dict)
        }
    except (OSError, ValueError):
        _HERO_LANE_TYPES_CACHE = {}
    return _HERO_LANE_TYPES_CACHE


def subject_for(position, hero=None, player=None, hero_tags=None) -> str:
    """分路 → 评级主体 key。全项目唯一口径，前后端都按这套语义实现。

    打野的两档：
    1. 本局实际打野刀（player.blade.kind，营地 finalEquips 判定）优先——
       同一个英雄换出装要换口径；
    2. 拿不到打野刀时退回英雄在「打野」位上的静态标签（resources/hero_tags.json）——
       坦野 → 打野·坦野，其余（战野/刺野/法核等）→ 打野·野核。
    `hero_tags` 可传入同结构的映射，避免调用方重复读盘；不传则懒加载。
    已经是主体 key（如前端直接传 '打野·坦野'）时原样返回。
    """
    pos = str(position or '').strip()
    if pos in ('打野·坦野', '打野·野核'):
        return pos
    if pos != '打野':
        return pos if pos in SUBJECT_LABELS else ''
    blade = player.get('blade') if isinstance(player, dict) else None
    kind = blade.get('kind') if isinstance(blade, dict) else None
    if kind == 'tank':
        return '打野·坦野'
    if kind == 'core':
        return '打野·野核'
    tags = hero_tags if isinstance(hero_tags, dict) else _hero_lane_types()
    entry = tags.get(str(hero or '')) or {}
    # 两种传入形态都吃：hero_tags.json 的 {英雄: {'lanes': {...}}}，
    # 以及 _icon_metadata()['heroTypes'] 的 {英雄: {...}}（已剥掉 lanes 层）。
    lanes = entry.get('lanes') if isinstance(entry, dict) and isinstance(entry.get('lanes'), dict) else entry
    jungle_type = str((lanes.get('打野') if isinstance(lanes, dict) else '') or '')
    return '打野·坦野' if '坦野' in jungle_type else '打野·野核'
