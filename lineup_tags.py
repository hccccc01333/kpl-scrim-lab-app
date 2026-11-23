"""赛训组自定义「阵容标签」的存储与英雄名录。

模块八（2026-11，同月两次按反馈改版）：赛训组自己起标签（如「无前排」）并绑定
5 个英雄；前端为卡片墙展示 + 头像网格手动挑选，带分路筛选与赛事记录字段
（不再走口述文稿提取）。这里负责存储、内置标签种子（DEFAULT_TAGS，教练首次
保存前展示、可整体改）与英雄名录/分路（resources/hero_tags.json）。
ALIASES 保留：meta 接口口径不变，旧客户端仍能拿到同一张表。

口径与 combo_pool.py / grade_rules.py 保持一致：
- 数据落在 data/facts/lineup_tags.json，尊重 KPL_DATA_DIR 覆盖（bp_facts.FACTS）；
- 整体覆盖保存 + revision 乐观锁（由 v3/serve.py 的路由校验）；
- 每次保存前用 config_history.record('lineup_tags', ...) 留一条可追溯快照。
  注意不是既有配置名，所以不进 combo_pool/grade_rules 的历史白名单——
  这是刻意的：阵容标签是新功能，不改动别人在维护的配置页口径。

行结构：
  tags: [{id, name, heroes:[五个标准英雄名], note?, source:'manual'|'speech'|'builtin',
          competition?: {id, name, date}|null, createdAt?}]
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA = 'custom-lineup-tags-v1'
FILENAME = 'lineup_tags.json'
HEROES_PER_TAG = 5

# 语音转写 / 赛训口语里的简称、同音字 → resources/catalog.json 的标准英雄名。
# 只收有把握的映射；语音同音只列最常见的几个，识别不到的仍可手动补进英雄名单。
ALIASES = {
    # 通用简称（沿用组合池的口径）
    '大师': '鲁班大师',
    '元坦': '元流之子(坦克)', '源坦': '元流之子(坦克)',
    '元辅': '元流之子(辅助)', '源辅': '元流之子(辅助)',
    '熬影': '敖隐', '老虎': '裴擒虎', '宫本': '宫本武藏',
    '奕星': '弈星', '夏侯': '夏侯惇', '夏侯缘': '少司缘',
    '戈雅': '戈娅', '凯': '铠', '守约': '百里守约',
    '猫咪': '沈梦溪', '魔丸': '哪吒',
    # 口述转写常见同音 / 误听
    '盾三': '盾山', '杨简': '杨戬', '王昭军': '王昭君',
    '后毅': '后羿', '菜文姬': '蔡文姬', '廉坡': '廉颇',
    '张凉': '张良', '虞姬儿': '虞姬', '公孙梨': '公孙离',
    '朵丽亚': '朵莉亚', '大思命': '大司命', '少思缘': '少司缘',
    '沈孟溪': '沈梦溪', '裴擒虎儿': '裴擒虎',
}

# 内置阵容标签（2026-11-22 教练反馈：先给一套现成标签，教练可以改）。
# 英雄组合按 resources/hero_tags.json 的能力矩阵核对：无前排=前排 0、
# 单前排/双前排=前排 1/2、强开团=开团 2、四保一=保护 4、无控制=控制 0。
# 只在从未保存过时展示；教练点一次保存就整体落盘，之后完全以磁盘为准。
DEFAULT_TAGS = [
    {
        'id': 'lt-builtin-no-front', 'name': '无前排',
        'heroes': ['马可波罗', '不知火舞', '镜', '干将莫邪', '瑶'],
        'note': '全远程消耗，没有前排承伤位',
        'source': 'builtin', 'createdAt': '',
    },
    {
        'id': 'lt-builtin-one-front', 'name': '单前排',
        'heroes': ['吕布', '马可波罗', '不知火舞', '张良', '太乙真人'],
        'note': '坦边/坦野顶前排，后排输出',
        'source': 'builtin', 'createdAt': '',
    },
    {
        'id': 'lt-builtin-two-front', 'name': '双前排',
        'heroes': ['吕布', '夏侯惇', '后羿', '王昭君', '蔡文姬'],
        'note': '双坦边压制冲击阵',
        'source': 'builtin', 'createdAt': '',
    },
    {
        'id': 'lt-builtin-engage', 'name': '强开团',
        'heroes': ['关羽', '张飞', '娜可露露', '虞姬', '弈星'],
        'note': '关羽张飞双开团点，先手强开',
        'source': 'builtin', 'createdAt': '',
    },
    {
        'id': 'lt-builtin-four-protect-one', 'name': '四保一',
        'heroes': ['后羿', '蔡文姬', '明世隐', '太乙真人', '张飞'],
        'note': '后羿核心，四辅助保排',
        'source': 'builtin', 'createdAt': '',
    },
    {
        'id': 'lt-builtin-no-cc', 'name': '无控制',
        'heroes': ['马可波罗', '伽罗', '李元芳', '大司命', '露娜'],
        'note': '全输出无硬控，速推节奏',
        'source': 'builtin', 'createdAt': '',
    },
]


def path() -> Path:
    """跟 KPL 事实表同目录（bp_facts.FACTS），测试 monkeypatch FACTS 时自动隔离。"""
    import bp_facts
    return bp_facts.FACTS / FILENAME


def normalize(name: str) -> str:
    value = str(name or '').strip()
    return ALIASES.get(value, value)


def heroes_path() -> Path:
    return Path(__file__).resolve().parent / 'resources' / 'hero_tags.json'


def hero_names() -> list[str]:
    """头像挑选兜底名录用的英雄标准名（resources/hero_tags.json）。文件缺失时返回空表。"""
    file = heroes_path()
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        heroes = doc.get('heroes') or {}
        return sorted(str(name) for name in heroes if str(name).strip())
    except (OSError, ValueError):
        return []


def hero_lanes() -> dict[str, list[str]]:
    """英雄 → 分路列表（hero_tags.json 的 lanes 键），前端「筛选分路」用。
    一名英雄可走多条分路（如廉颇 对抗路+游走），全部列出。"""
    file = heroes_path()
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        out = {}
        for name, hero in (doc.get('heroes') or {}).items():
            lanes = [str(lane) for lane in (hero.get('lanes') or {}) if lane]
            if lanes:
                out[str(name)] = lanes
        return out
    except (OSError, ValueError):
        return {}


def _default_doc() -> dict:
    return {'schema': SCHEMA, 'revision': 0, 'updatedAt': '', 'tags': [], 'saved': False}


def _builtin_doc() -> dict:
    """没保存过时给内置标签（revision 0，不落盘；教练首次保存即整体覆盖）。"""
    return {'schema': SCHEMA, 'revision': 0, 'updatedAt': '', 'saved': False,
            'builtin': True, 'tags': [dict(row) for row in DEFAULT_TAGS]}


def _valid(doc) -> bool:
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        return False
    rows = doc.get('tags')
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if not str(row.get('name') or '').strip():
            return False
        heroes = row.get('heroes')
        if not isinstance(heroes, list) or len(heroes) != HEROES_PER_TAG:
            return False
        if any(not str(h or '').strip() for h in heroes):
            return False
        if len({str(h).strip() for h in heroes}) != HEROES_PER_TAG:
            return False
    return True


def read_saved() -> dict | None:
    """只读磁盘上已保存的标签；没保存过或文件损坏返回 None。"""
    file = path()
    if not file.exists():
        return None
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        return doc if _valid(doc) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    """给设置页用：已保存就读磁盘；没保存过返回内置标签（不落盘，教练可改）。"""
    doc = read_saved()
    if doc is None:
        return _builtin_doc()
    return {**doc, 'saved': True}


def _competition_of(row: dict) -> dict | None:
    """赛事记录（可选）：只留 id / name / date 三个字段，缺失或格式不对时归 None。"""
    comp = row.get('competition')
    if not isinstance(comp, dict):
        return None
    comp_id = str(comp.get('id') or '').strip()
    if not comp_id:
        return None
    return {
        'id': comp_id,
        'name': str(comp.get('name') or '').strip(),
        'date': str(comp.get('date') or '').strip(),
    }


def _summary(old: dict | None, new: dict) -> str:
    before = {str(row.get('id')): row for row in (old or {}).get('tags') or []}
    after = {str(row.get('id')): row for row in new.get('tags') or []}
    added = [row for key, row in after.items() if key not in before]
    removed = [row for key, row in before.items() if key not in after]
    changed = [row for key, row in after.items()
               if key in before and before[key] != row]
    bits = []
    if added:
        bits.append('新增「' + '、'.join(str(r.get('name') or '') for r in added[:3]) + '」')
    if removed:
        bits.append('删除 ' + str(len(removed)) + ' 个标签')
    if changed:
        bits.append('修改「' + '、'.join(str(r.get('name') or '') for r in changed[:3]) + '」')
    return '；'.join(bits) if bits else '阵容标签已更新'


def save(doc: dict, bump: bool = True, summary: str = '') -> dict:
    """整体覆盖保存；bump 时 revision +1（乐观锁由调用方在保存前校验）。"""
    if not _valid(doc):
        raise ValueError(f'阵容标签格式不正确：每个标签需要名称 + {HEROES_PER_TAG} 个不同英雄')
    import config_history
    old = read_saved()
    config_history.record('lineup_tags', old, doc, summary or _summary(old, doc))
    from datetime import datetime, timezone
    out = {
        'schema': SCHEMA,
        'revision': int(doc.get('revision') or 0) + (1 if bump else 0),
        'updatedAt': doc.get('updatedAt') or datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'tags': [
            {
                'id': str(row.get('id') or ''),
                'name': str(row.get('name') or '').strip(),
                'heroes': [str(h).strip() for h in row['heroes']],
                'note': str(row.get('note') or '').strip(),
                'source': str(row.get('source') or 'manual'),
                'competition': _competition_of(row),
                'createdAt': str(row.get('createdAt') or ''),
            }
            for row in doc['tags']
        ],
    }
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='lineup_tags-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(out, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out
