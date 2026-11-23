"""赛训组「自家克制库」数据层（模块九前半，不含 BP 模拟 UI）。

为什么要另起一套（先核对现状，只补缺口）：
- 项目里已经有两份克制数据，但都不是「赛训组自己的」：
  * data/facts/camp_counters.json  —— 王者营地 App 英雄关系（官方编辑口径，无样本量）。
    教练口径：巅峰千分 / 王者营地**最不准**（赵云克守约 / 墨子克达摩 / 武则天克芈月等已被否）。
  * data/facts/kpl_counters.json   —— KPL 官方赛事跨阵营有向对位（有样本量），**相对准**。
  * bp_facts._counter_block() 的「命中克制」目前只查这两套（camp + kpl），没有自家口径。
- 所以这里新建第三套：**自家克制库**，与营地数据彻底分开（赛训另搞一套），
  命中时通过 source='own' 标识，前端/下一批 BP 模拟可把它和 campHit / kplHit 分开显示。

业务口径：
1. 先用 KPL 数据生成初稿（相对准），教练可删改；
2. 版本变动后用 regenerate() 重做克制对（会覆盖人工删改，config_history 留旧快照可回滚）；
3. 数据指向训练赛：scope='training'，每条克制对带 trainingMatches（验证过这对克制的训练赛 id），
   克制关系由训练赛复盘沉淀，不是给巅峰千分 / 营地背书；
4. "贴膜" 数据源最准但**待确认**，暂不接入——SOURCE_RELIABILITY 里留了坑位，确认后替换 draft 源即可。

口径与 combo_pool.py / lineup_tags.py 保持一致：
- 数据落 data/facts/counter_library.json，尊重 KPL_DATA_DIR 覆盖（bp_facts.FACTS）；
- 整体覆盖保存 + revision 乐观锁（由 v3/serve.py 路由校验）；
- 每次保存前 config_history.record('counter_library', ...) 留一条可追溯快照。

行结构（有向：a 克 b）：
  pairs: [{id, a, b, n?, wins?, wr?, lastDate?, year?, source:'kpl-draft'|'manual',
           trainingMatches:[训练赛 id], note?, createdAt?}]
对外 hit(a, b) 只认已保存且非空的库，返回带 source='own' 的行，供命中克制区分来源。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA = 'custom-counter-library-v1'
FILENAME = 'counter_library.json'
SCOPE = 'training'                     # 数据指向训练赛：赛训复盘口径，不是排位/营地口径
KPL_SOURCE_FILE = 'kpl_counters.json'  # 初稿数据源（相对准；"贴膜" 待确认后再换）

# 数据源可靠性（教练口径，rank 越小越准；"自家库"另标运营优先级）。
# 只做标注，不在此模块合成任何"统一分"——命中克制必须分来源显示。
SOURCE_RELIABILITY = {
    'tiemo': {'label': '贴膜', 'rank': 1, 'note': '口径最准，但数据源待确认，暂未接入；确认后替换初稿源'},
    'own': {'label': '自家克制库（赛训）', 'rank': 2, 'note': '运营口径以此为准：赛训组自己维护、指向训练赛；初稿来自 KPL，教练删改后覆盖'},
    'kpl': {'label': 'KPL 官方赛事', 'rank': 3, 'note': '相对准，当前初稿数据源（跨阵营有向对位，有样本量）'},
    'peak': {'label': '巅峰千分', 'rank': 4, 'note': '最不准，不采用（英雄强弱污染对位，冷门样本少）'},
    'camp': {'label': '王者营地', 'rank': 4, 'note': '最不准，不采用（赵云克守约/墨子克达摩/武则天克芈月等被否）'},
}

# 简称 → 英雄库标准名（沿用 combo_pool / lineup_tags 的口径，只收有把握的映射）。
ALIASES = {
    '大师': '鲁班大师', '元坦': '元流之子(坦克)', '源坦': '元流之子(坦克)',
    '元辅': '元流之子(辅助)', '源辅': '元流之子(辅助)', '熬影': '敖隐',
    '老虎': '裴擒虎', '宫本': '宫本武藏', '奕星': '弈星', '夏侯': '夏侯惇',
    '戈雅': '戈娅', '凯': '铠', '守约': '百里守约', '猫咪': '沈梦溪',
    '魔丸': '哪吒',
}

# KPL 初稿的命中门槛：与 bp_facts 的 KPL_HIT_N / KPL_HIT_WR 对齐。
# bp_facts 不可导入时用同值兜底；教练可在生成脚本里显式传参覆盖。
try:
    import bp_facts as _bp_facts
    _DEFAULT_MIN_N = int(getattr(_bp_facts, 'KPL_HIT_N', 10))
    _DEFAULT_HIT_WR = float(getattr(_bp_facts, 'KPL_HIT_WR', 55.0))
except (ImportError, OSError, ValueError):  # pragma: no cover - 独立脚本场景
    _bp_facts = None
    _DEFAULT_MIN_N, _DEFAULT_HIT_WR = 10, 55.0


def path() -> Path:
    """跟 KPL 事实表同目录（bp_facts.FACTS），测试 monkeypatch FACTS 时自动隔离。"""
    import bp_facts
    return bp_facts.FACTS / FILENAME


def normalize(name: str) -> str:
    value = str(name or '').strip()
    return ALIASES.get(value, value)


def _default_doc(note: str = '') -> dict:
    """可手工维护的空库（KPL 数据不可得时的兜底，绝不编造克制对）。"""
    return {
        'schema': SCHEMA, 'revision': 0, 'updatedAt': '', 'saved': False,
        'scope': SCOPE, 'source': 'empty', 'version': '',
        'sourceNote': note or (
            '空库：暂未生成初稿。可在设置页手工添加克制对（a 克 b），'
            '或点「用 KPL 重做克制对」从 KPL 赛事数据生成初稿。'),
        'draftFrom': None, 'pairs': [],
    }


def _valid(doc) -> bool:
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        return False
    rows = doc.get('pairs')
    if not isinstance(rows, list):
        return False
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return False
        a = normalize(row.get('a'))
        b = normalize(row.get('b'))
        if not a or not b or a == b:
            return False
        if (a, b) in seen:          # 同一对不重复，避免命中判定歧义
            return False
        seen.add((a, b))
        matches = row.get('trainingMatches')
        if matches is not None and not isinstance(matches, list):
            return False
    return True


def read_saved() -> dict | None:
    """只读磁盘上已保存的库；没保存过或文件损坏返回 None。"""
    file = path()
    if not file.exists():
        return None
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
        return doc if _valid(doc) else None
    except (OSError, ValueError):
        return None


def load() -> dict:
    """设置页/API 用：已保存就读磁盘，没保存过返回空库（不落盘）。"""
    doc = read_saved()
    if doc is None:
        return _default_doc()
    return {**doc, 'saved': True}


def has_saved() -> bool:
    """是否已有赛训组保存过的克制库（含空库也算已保存，表示教练确认过）。"""
    return read_saved() is not None


def build_draft(*, version: str = '', min_n: int | None = None,
                hit_wr: float | None = None) -> dict:
    """从现有 KPL 数据算克制对，生成初稿（**不落盘**，供预览或 regenerate 调用）。

    数据源 data/facts/kpl_counters.json（KPL 官方赛事跨阵营有向对位）：
    一行 (a, b, n, wins, wr) 表示「a 对上 b 共 n 场，a 胜 wr%」。
    取 n >= min_n 且 wr >= hit_wr 的行作为「a 克 b」初稿候选——
    两个方向各有自己的胜率，门槛天然只会选出占优的那一侧，不会双向重复。

    数据不可得（文件缺失 / 格式异常 / 空表）时返回带说明的空库：
    宁可给教练一个能手工维护的空库，也不编造克制对。
    """
    import bp_facts
    min_n = _DEFAULT_MIN_N if min_n is None else int(min_n)
    hit_wr = _DEFAULT_HIT_WR if hit_wr is None else float(hit_wr)
    base = read_saved() or _default_doc()

    source_file = bp_facts.FACTS / KPL_SOURCE_FILE
    try:
        data = json.loads(source_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = None

    if not isinstance(data, dict) or not isinstance(data.get('pairs'), list):
        empty = _default_doc('KPL 初稿数据源 kpl_counters.json 不可读/为空：'
                             '已给出空库，可手工添加克制对；数据可用后再点重做。')
        empty['revision'] = int(base.get('revision') or 0)
        empty['version'] = str(version or '')
        return empty

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    candidates = []
    index = 0
    for row in data['pairs']:
        if not isinstance(row, dict):
            continue
        a, b = normalize(row.get('a')), normalize(row.get('b'))
        try:
            n = int(row.get('n') or 0)
            wr = float(row.get('wr')) if row.get('wr') is not None else None
        except (TypeError, ValueError):
            continue
        if not a or not b or a == b or wr is None or n < min_n or wr < hit_wr:
            continue
        index += 1
        candidates.append({
            'id': f'kpl{index}', 'a': a, 'b': b,
            'n': n, 'wins': row.get('wins'), 'wr': round(wr, 1),
            'year': row.get('year'), 'lastDate': row.get('lastDate'),
            'source': 'kpl-draft', 'trainingMatches': [], 'note': '',
            'createdAt': now,
        })
    candidates.sort(key=lambda item: (-item['wr'], -item['n'], item['a']))

    return {
        'schema': SCHEMA, 'revision': int(base.get('revision') or 0),
        'updatedAt': '', 'saved': False,
        'scope': SCOPE, 'source': 'kpl-draft' if candidates else 'empty',
        'version': str(version or ''),
        'sourceNote': (
            f'KPL 赛事初稿：n>={min_n} 且胜率>={hit_wr}% 判为「a 克 b」。'
            'KPL 相对准但非最终口径；教练可删改，并用训练赛复盘验证（trainingMatches）。'
            '巅峰千分/王者营地最不准，不采用；"贴膜"待确认。'
        ),
        'draftFrom': {
            'file': KPL_SOURCE_FILE,
            'games': data.get('games'), 'minN': data.get('minN'),
            'windowStart': data.get('windowStart'), 'windowEnd': data.get('windowEnd'),
            'generatedAt': now, 'minNUsed': min_n, 'hitWrUsed': hit_wr,
        },
        'pairs': candidates,
    }


def regenerate(*, version: str = '', min_n: int | None = None,
               hit_wr: float | None = None) -> dict:
    """版本变动后重做克制对：用 KPL 数据生成初稿并保存。

    会覆盖教练此前的删改——这是刻意的（版本变了旧克制对失效）；
    旧库在保存前由 save() 记进 config_history，可回滚。
    """
    return save(build_draft(version=version, min_n=min_n, hit_wr=hit_wr),
                summary=f'用 KPL 重做克制对（版本 {version or "未标注"}）')


def _summary(old: dict | None, new: dict) -> str:
    before = {(normalize(r.get('a')), normalize(r.get('b'))): r
              for r in (old or {}).get('pairs') or []}
    after = {(normalize(r.get('a')), normalize(r.get('b'))): r
             for r in new.get('pairs') or []}
    added = [key for key in after if key not in before]
    removed = [key for key in before if key not in after]
    changed = [key for key in after if key in before and before[key] != after[key]]
    bits = []
    if added:
        bits.append('新增 ' + '、'.join(f'{a}克{b}' for a, b in added[:3]))
    if removed:
        bits.append('删除 ' + str(len(removed)) + ' 对')
    if changed:
        bits.append('修改 ' + '、'.join(f'{a}克{b}' for a, b in changed[:3]))
    if new.get('version') and (old or {}).get('version') != new.get('version'):
        bits.append('版本→' + str(new['version']))
    return '；'.join(bits) if bits else '自家克制库已更新'


def save(doc: dict, bump: bool = True, summary: str = '') -> dict:
    """整体覆盖保存；bump 时 revision +1（乐观锁由调用方在保存前校验）。"""
    if not _valid(doc):
        raise ValueError('克制库格式不正确：每条需有 a/b 两个不同英雄且不重复，trainingMatches 须为数组')
    import config_history
    old = read_saved()
    config_history.record('counter_library', old, doc, summary or _summary(old, doc))
    from datetime import datetime, timezone
    out = {
        'schema': SCHEMA,
        'revision': int(doc.get('revision') or 0) + (1 if bump else 0),
        'updatedAt': doc.get('updatedAt') or datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'scope': SCOPE,
        'source': str(doc.get('source') or 'manual'),
        'version': str(doc.get('version') or ''),
        'sourceNote': str(doc.get('sourceNote') or ''),
        'draftFrom': doc.get('draftFrom'),
        'pairs': [
            {
                'id': str(row.get('id') or ''),
                'a': normalize(row['a']), 'b': normalize(row['b']),
                'n': row.get('n'), 'wins': row.get('wins'), 'wr': row.get('wr'),
                'year': row.get('year'), 'lastDate': row.get('lastDate'),
                'source': str(row.get('source') or 'manual'),
                'trainingMatches': [str(m) for m in (row.get('trainingMatches') or [])],
                'note': str(row.get('note') or ''),
                'createdAt': str(row.get('createdAt') or ''),
            }
            for row in doc['pairs']
        ],
    }
    out['pairs'].sort(key=lambda r: (-(float(r['wr']) if r.get('wr') is not None else -1),
                                     -(int(r['n']) if r.get('n') else 0), r['a']))
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='counter_library-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(out, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out


def table() -> dict[tuple[str, str], dict]:
    """(a, b) → 行（有向：a 克 b）。只认赛训组真正保存过的库；未保存返回空表。"""
    doc = read_saved()
    if not doc:
        return {}
    return {(normalize(row['a']), normalize(row['b'])): row for row in doc.get('pairs') or []}


def hit(a: str, b: str) -> dict | None:
    """我方 a 对敌方 b 是否命中**自家克制库**。

    返回行带 source='own' 与 verdict='我方克制'，供下一批「命中克制」UI
    与营地 (campHit) / KPL (kplHit) 分开显示；未命中返回 None。
    """
    row = table().get((normalize(a), normalize(b)))
    if not row:
        return None
    return {**row, 'source': 'own', 'verdict': '我方克制'}


def link_match(a: str, b: str, match_id: str) -> dict | None:
    """把一对克制指向训练赛（去重），返回整份新文档；找不到该对返回 None。
    调用方拿到返回值后走 save() 落盘（revision 乐观锁仍由 API 校验）。"""
    doc = read_saved()
    if not doc:
        return None
    key = (normalize(a), normalize(b))
    for row in doc.get('pairs') or []:
        if (normalize(row.get('a')), normalize(row.get('b'))) == key:
            matches = row.setdefault('trainingMatches', [])
            if match_id and match_id not in matches:
                matches.append(str(match_id))
            return doc
    return None
