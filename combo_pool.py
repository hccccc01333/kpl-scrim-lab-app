"""赛训组自定义组合池：双人组合 / 三人体系。

口径（2026-11-21）：
- 这是**赛训组自己的组合名单**，优先级高于 KPL 事实表与营地现场归并。
  只要池子非空，「组合命中 / 我方敌方组合 / 拆组合 / 双人组合 / 三人体系」
  都只认这里的名单；KPL 的场次与胜率只作为背景统计挂在同一行上，不参与名单判定。
- 池子为空时才退回原来的 KPL / 营地口径，保证旧实例照常工作。
- 数据落在 data/combo_pool.json，尊重 KPL_DATA_DIR 覆盖，赛训组在设置页增删改。

行结构：
  pairs: [{id, heroes:[两个标准英雄名], strength:'strong'|'weak', name?, note?}]
  trios: [{id, heroes:[三个标准英雄名], name?, note?}]
对外 index() 会把每行补成 KPL 组合库同构的行（heroes/n/wins/wr/year/lastDate/teams），
外加 source='custom' 与 strength，方便各页面直接消费。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA = 'custom-combos-v1'
FILENAME = 'combo_pool.json'

# Excel 里的简称 → 英雄库标准名（resources/catalog.json）。
# 只映射确定能一一对应的；"猫咪 / 魔丸" 是绰号，置信度中低，仍映射但在 note 里留痕，
# 赛训组可在设置页直接改名改头像。
ALIASES = {
    '大师': '鲁班大师',
    '元坦': '元流之子(坦克)',
    '源坦': '元流之子(坦克)',
    '元辅': '元流之子(辅助)',
    '源辅': '元流之子(辅助)',
    '熬影': '敖隐',
    '老虎': '裴擒虎',
    '宫本': '宫本武藏',
    '奕星': '弈星',
    '夏侯': '夏侯惇',
    '夏侯缘': '少司缘',   # Excel 原表写法，实际英雄是少司缘
    '戈雅': '戈娅',
    '凯': '铠',
    '守约': '百里守约',
    '猫咪': '沈梦溪',     # 绰号「炸弹猫」，保留 note 供核对
    '魔丸': '哪吒',       # 绰号「魔丸」，保留 note 供核对
}

# 内置默认双人组合：来自赛训组提供的「全英雄组合.xlsx」Sheet1。
# (英雄 A, 英雄 B, 联动强弱) —— 强弱照抄原表，不去自行推断。
BUILTIN_PAIRS = [
    ('钟馗', '小乔', 'weak'),
    ('鲁班大师', '元流之子(坦克)', 'strong'),
    ('鲁班大师', '黄忠', 'strong'),
    ('狄仁杰', '元流之子(辅助)', 'strong'),
    ('敖隐', '元流之子(辅助)', 'weak'),
    ('钟馗', '安琪拉', 'weak'),
    ('鲁班大师', '狄仁杰', 'strong'),
    ('鲁班大师', '鲁班七号', 'strong'),
    ('盾山', '艾琳', 'strong'),
    ('盾山', '曹操', 'weak'),
    ('孙膑', '虞姬', 'weak'),
    ('孙膑', '白起', 'strong'),
    ('沈梦溪', '裴擒虎', 'weak'),
    ('宫本武藏', '吕布', 'weak'),
    ('宫本武藏', '弈星', 'weak'),
    ('夏侯惇', '安琪拉', 'weak'),
    ('苏烈', '戈娅', 'weak'),
    ('女娲', '空空儿', 'weak'),
    ('空空儿', '戈娅', 'weak'),
    ('苏烈', '司空震', 'weak'),
    ('关羽', '铠', 'strong'),
    ('少司缘', '公孙离', 'strong'),
    ('少司缘', '大司命', 'strong'),
    ('少司缘', '桑启', 'weak'),
    ('少司缘', '沈梦溪', 'weak'),
    ('张良', '安琪拉', 'strong'),
    ('张良', '王昭君', 'strong'),
    ('少司缘', '王维', 'weak'),
    ('少司缘', '狄仁杰', 'weak'),
    ('蔡文姬', '百里守约', 'strong'),
    ('墨子', '虞姬', 'strong'),
    ('盾山', '虞姬', 'weak'),
    ('朵莉亚', '杨戬', 'weak'),
    ('朵莉亚', '海月', 'strong'),
    ('阿古朵', '马超', 'strong'),
    ('空空儿', '武则天', 'weak'),
    ('盾山', '司空震', 'weak'),
    ('太乙真人', '孙尚香', 'strong'),
    ('明世隐', '孙尚香', 'strong'),
    ('刘邦', '哪吒', 'strong'),
    ('刘邦', '镜', 'strong'),
    ('鲁班大师', '赵云', 'weak'),
]

# 内置三人体系：赛训组聊天里明确「先就写一个」的流星锤组合。
BUILTIN_TRIOS = [
    (['鲁班大师', '元流之子(坦克)', '司空震'], '流星锤组合', 'strong'),
]

# 绰号映射留痕：这些行的 note 会提示赛训组核对名字。
_ALIAS_NOTE = {'沈梦溪': '原表写「猫咪」，按炸弹猫映射，请核对',
               '哪吒': '原表写「魔丸」，按魔丸映射，请核对'}


def path() -> Path:
    """跟 KPL 事实表同目录（bp_facts.FACTS），测试 monkeypatch 到 tmp_path 时自动隔离。"""
    import bp_facts
    return bp_facts.FACTS / FILENAME


def normalize(name: str) -> str:
    value = str(name or '').strip()
    return ALIASES.get(value, value)


def _default_doc() -> dict:
    pairs = []
    for index, (a, b, strength) in enumerate(BUILTIN_PAIRS, 1):
        heroes = [normalize(a), normalize(b)]
        note = '；'.join(_ALIAS_NOTE[h] for h in heroes if h in _ALIAS_NOTE)
        row = {'id': f'p{index}', 'heroes': heroes, 'strength': strength}
        if note:
            row['note'] = note
        pairs.append(row)
    trios = [{'id': f't{index}', 'heroes': list(heroes), 'name': name, 'strength': strength}
             for index, (heroes, name, strength) in enumerate(BUILTIN_TRIOS, 1)]
    return {'schema': SCHEMA, 'revision': 1, 'updatedAt': '',
            'pairs': pairs, 'trios': trios, 'builtin': True}


def _valid(doc) -> bool:
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        return False
    for key, size in (('pairs', 2), ('trios', 3)):
        rows = doc.get(key)
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, dict):
                return False
            heroes = row.get('heroes')
            if not isinstance(heroes, list) or len(heroes) != size:
                return False
            if any(not str(h or '').strip() for h in heroes):
                return False
    return True


def read_saved() -> dict | None:
    """只读磁盘上已保存的池子；没保存过返回 None。

    优先级注入只认这个函数：内置默认只是给设置页展示的种子，用户没点保存之前
    不参与任何分析口径。这样测试把 FACTS 指到空 tmp_path 时不会凭空多出组合。
    """
    file = path()
    if not file.exists():
        return None
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        return doc if _valid(doc) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    """给设置页用：已保存就读磁盘，没保存过返回内存里的内置默认（不落盘）。"""
    return read_saved() or _default_doc()


def save(doc: dict, bump: bool = True, summary: str = '') -> dict:
    """整体覆盖保存；bump 时按 revision 乐观锁由调用方校验后再递增。"""
    if not _valid(doc):
        raise ValueError('组合池数据格式不正确')
    import config_history
    config_history.record('combo_pool', read_saved(), doc,
                          summary or config_history.diff_summary('combo_pool', read_saved(), doc))
    out = {'schema': SCHEMA,
           'revision': int(doc.get('revision') or 0) + (1 if bump else 0),
           'updatedAt': doc.get('updatedAt') or '',
           'pairs': [row for row in doc['pairs']],
           'trios': [row for row in doc['trios']]}
    if not out['updatedAt']:
        from datetime import datetime, timezone
        out['updatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='combo_pool-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(out, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out


def rows(size: int, saved_only: bool = False) -> list[dict]:
    """saved_only=True 时只读用户真正保存过的组合； False 时含内置默认（仅展示用）。"""
    doc = read_saved() if saved_only else load()
    if not doc:
        return []
    key = 'pairs' if size == 2 else 'trios'
    return [dict(row) for row in (doc.get(key) or [])]


def tables() -> tuple[dict, dict]:
    """按键（排序后的英雄元组）建表，供命中判定直接查；只认用户保存过的组合。"""
    pairs, trios = {}, {}
    for size, out in ((2, pairs), (3, trios)):
        for row in rows(size, saved_only=True):
            heroes = tuple(sorted(normalize(h) for h in row['heroes']))
            out[heroes] = row
    return pairs, trios


def has_saved() -> bool:
    doc = read_saved()
    return bool(doc and ((doc.get('pairs') or []) or (doc.get('trios') or [])))
