"""首次安装把「内置数据」落盘成真正的配置，让新机器开箱即用。

背景（2026-11-24 打包问题排查）：
- 发布包原本只带程序代码 + resources/，data/ 是空骨架；
- combo_pool / lineup_tags / grade_rules 的内置种子只存在代码里，未保存时
  「命中判定 / 评级」一律不认；counter_library 更是空库；
- 规则中心克制关系读 data/facts/rules_counters.json，缺文件就是空表；
- 只有 resources/hero_tags.json 随包发布，所以演示时「英雄标签有、其它都没有」。

本模块在**真实服务启动**时跑一次（server.py __main__），把内置数据复制 /
保存为 data/facts 下的正式配置：
- 只在目标文件不存在时写，**绝不覆盖赛训组已保存的数据**；
- 落盘后这些配置就是「用户配置」：设置页可增删改，analysis 正常消费；
- 种子文件随 resources/ 一起发布，事实表与代码版本同步。

手动补种：``python builtin_seed.py``（幂等，已存在的跳过）。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED_ROOT = ROOT / 'resources' / 'builtin'
FACT_SEEDS = SEED_ROOT / 'facts'
CONFIG_SEEDS = SEED_ROOT / 'configs'
# 外部口径的原始语料：KPL 逐局 BP、巅峰千强日线 / 对位分片 / 爬取状态。
# 没有它们，英雄榜的 KPL 胜率 / 国服战力 / 大盘梯度要么空着，要么一刷新就没。
TREE_SEEDS = (
    (SEED_ROOT / 'kpl', 'kpl'),
    (SEED_ROOT / 'peak', 'peak'),
)
# 离线小缓存：英雄名映射（hero_catalog 无网时用它，否则一进复盘就请求官网）、
# KPL 抓取清单（窗口 / 赛季 / 错误统计）。
MISC_SEEDS = ('hero_list.json', 'manifest.json')
MISC_TARGETS = {'hero_list.json': 'hero_list.json', 'manifest.json': 'kpl/manifest.json'}

# 随包发布的事实表（KPL 组合 / 克制 / 对位 / 外部统计）。文件名即落盘名。
FACT_FILES = (
    'kpl_combos.json', 'kpl_counters.json', 'lane_matchups.json', 'hero_external_stats.json',
)
# 规则中心的两份内置种子（从 KPL 初稿生成，已随包固化，安装时不现算）。
SEEDED_CONFIGS = (
    ('counter_library.json', 'counter_library.seed.json'),
    ('rules_counters.json', 'rules_counters.seed.json'),
)


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='builtin-seed-', suffix='.json', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _seed_fact(facts: Path, name: str) -> bool:
    target = facts / name
    if target.is_file():
        return False
    source = FACT_SEEDS / name
    if not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _seed_tree(source: Path, target: Path) -> list[str]:
    """整棵目录补种：只复制目标里还不存在的文件，不覆盖已存在的语料。"""
    seeded = []
    if not source.is_dir():
        return seeded
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        destination = target / path.relative_to(source)
        if destination.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        seeded.append(str(destination.relative_to(target.parent)))
    return seeded


def _seed_config_from_file(facts: Path, target_name: str, seed_name: str) -> bool:
    target = facts / target_name
    if target.is_file():
        return False
    source = CONFIG_SEEDS / seed_name
    if not source.is_file():
        return False
    try:
        doc = json.loads(source.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    _atomic_write_json(target, doc)
    return True


def _seed_code_defaults(facts: Path) -> list[str]:
    """组合池 / 阵容标签 / 评级规则：直接用模块里的内置默认落盘。"""
    seeded = []
    try:
        import combo_pool
        if not combo_pool.path().is_file():
            combo_pool.save(combo_pool._default_doc(), bump=False)
            seeded.append('combo_pool.json')
    except Exception:                                # noqa: BLE001 - 单个配置失败不挡其它
        pass
    try:
        import lineup_tags
        if not lineup_tags.path().is_file():
            lineup_tags.save(lineup_tags._builtin_doc(), bump=False)
            seeded.append('lineup_tags.json')
    except Exception:                                # noqa: BLE001
        pass
    try:
        import grade_rules
        if not grade_rules.path().is_file():
            grade_rules.save(grade_rules._default_doc(), bump=False)
            seeded.append('grade_rules.json')
    except Exception:                                # noqa: BLE001
        pass
    return seeded


def _seed_rules_center_from_builtins(facts: Path) -> list[str]:
    """规则中心「组合体系 / 阵容标签」两张表：从对应的内置种子搬一份起点。"""
    seeded = []
    combos = facts / 'rules_combos.json'
    tags = facts / 'rules_lineup_tags.json'
    try:
        import combo_pool
        if not combos.is_file():
            rows = []
            for size, key in ((2, 'pairs'), (3, 'trios')):
                for i, row in enumerate(combo_pool.rows(size), 1):
                    rows.append({'id': f'{key}-{i}', 'heroes': list(row['heroes']),
                                 'strength': row.get('strength') or '',
                                 'name': row.get('name') or '', 'note': row.get('note') or '',
                                 'effective': {'eventId': '', 'eventName': '', 'from': '', 'to': ''}})
            _atomic_write_json(combos, {'schema': 'rules-center-combos-v1', 'revision': 0,
                                        'updatedAt': '', 'saved': False, 'combos': rows})
            seeded.append('rules_combos.json')
    except Exception:                                # noqa: BLE001
        pass
    try:
        import lineup_tags
        if not tags.is_file():
            rows = [{'id': r.get('id') or f'lt-{i}', 'name': r['name'],
                     'heroes': list(r['heroes']), 'note': r.get('note') or '',
                     'source': 'builtin',
                     'effective': {'eventId': '', 'eventName': '', 'from': '', 'to': ''}}
                    for i, r in enumerate(lineup_tags.DEFAULT_TAGS, 1)]
            _atomic_write_json(tags, {'schema': 'rules-center-lineup-tags-v1', 'revision': 0,
                                      'updatedAt': '', 'saved': False, 'tags': rows})
            seeded.append('rules_lineup_tags.json')
    except Exception:                                # noqa: BLE001
        pass
    return seeded


def _normalize_seeded_counters(facts: Path) -> bool:
    """旧包的 KPL 种子带 2026-01~10 生效窗，选 11 月赛事时全被过滤成空表。

    种子已改成常年生效；这里给装过旧包的机器做一次幂等迁移。只动未被赛训组
    改过的行（source=kpl-seed、id 以 kplseed- 开头、条目 revision<=1），
    手工新增 / 改过的行一律不碰。
    """
    target = facts / 'rules_counters.json'
    if not target.is_file():
        return False
    try:
        doc = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    changed = False
    for key in ('heroPairs', 'comboPairs'):
        for row in doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get('source') or '') != 'kpl-seed':
                continue
            if not str(row.get('id') or '').startswith('kplseed-'):
                continue
            try:
                if int(row.get('revision') or 0) > 1:
                    continue
            except (TypeError, ValueError):
                continue
            eff = row.get('effective') or {}
            if any(str(eff.get(k) or '').strip() for k in ('eventId', 'eventName', 'from', 'to')):
                row['effective'] = {'eventId': '', 'eventName': '', 'from': '', 'to': ''}
                changed = True
    if not changed:
        return False
    doc['saved'] = True
    _atomic_write_json(target, doc)
    return True


def ensure_all(*, verbose: bool = False) -> dict:
    """幂等补种；返回 {'facts': 目录, 'seeded': [...], 'skipped': [...]}。"""
    import bp_facts
    facts = Path(bp_facts.FACTS)
    facts.mkdir(parents=True, exist_ok=True)
    seeded, skipped = [], []
    for source, subdir in TREE_SEEDS:
        seeded.extend(_seed_tree(source, facts.parent / subdir))
    for name in MISC_SEEDS:
        source = SEED_ROOT / 'misc' / name
        target = facts.parent / MISC_TARGETS[name]
        if source.is_file() and not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            seeded.append(MISC_TARGETS[name])
    for name in FACT_FILES:
        (seeded if _seed_fact(facts, name) else skipped).append(name)
    for target, seed in SEEDED_CONFIGS:
        (seeded if _seed_config_from_file(facts, target, seed) else skipped).append(target)
    _normalize_seeded_counters(facts)
    for name in _seed_code_defaults(facts):
        seeded.append(name)
    for name in ('combo_pool.json', 'lineup_tags.json', 'grade_rules.json'):
        if name not in seeded and (facts / name).is_file():
            skipped.append(name)
    for name in _seed_rules_center_from_builtins(facts):
        seeded.append(name)
    for name in ('rules_combos.json', 'rules_lineup_tags.json'):
        if name not in seeded and (facts / name).is_file():
            skipped.append(name)
    report = {'facts': str(facts), 'seeded': seeded, 'skipped': skipped}
    if verbose:
        print(f'[内置数据] 补种 {len(seeded)} 份，已存在跳过 {len(skipped)} 份：{facts}')
    return report


if __name__ == '__main__':
    ensure_all(verbose=True)
