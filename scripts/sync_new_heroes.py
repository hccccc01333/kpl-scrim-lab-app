"""把新英雄同步进项目的全部英雄名录（一份命令，重复执行安全）。

为什么需要它
------------
英雄信息分散在几处，漏一处就会出现「头像挑不到 / OCR 认不出 / 面板没分路」：
* resources/catalog.json + resources/icons/hero-<id>.png —— 头像、OCR 名录
* resources/hero_tags.json                         —— 头像挑选名录、分路、10 分钟评级
* data/hero_list.json（及随包种子）                —— heroId → 英雄名缓存
* 91m 事实表（巅峰千强 / 国服战力）                —— 由 peak_crawl 每日自动刷新，不用本脚本

数据源是王者荣耀官方 herolist.json（联网）；离线时用 data/hero_list.json 缓存补名字。
默认分路先按官方 roles / 巅峰千强分路池猜一个，赛训类型一律「待分类」、能力矩阵全 0，
**不猜教练口径**。赛训组补完工作簿后跑 scripts/import_hero_labels.py 与
scripts/rebuild_hero_roles.py，把 archetype / capability / roles 三张表也补齐。

用法：
    python scripts/sync_new_heroes.py                     # 只报告差异，不写
    python scripts/sync_new_heroes.py --apply             # 写入全部缺的英雄
    python scripts/sync_new_heroes.py --apply --only 刀锋宝贝
    python scripts/sync_new_heroes.py --apply --offline   # 无网：只补名字，不抓头像
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERO_URL = 'https://pvp.qq.com/web201605/js/herolist.json'
ICON_URL = 'https://game.gtimg.cn/images/yxzj/img201606/heroimg/{hid}/{hid}.jpg'
CATALOG = ROOT / 'resources' / 'catalog.json'
ICONS = ROOT / 'resources' / 'icons'
TAGS = ROOT / 'resources' / 'hero_tags.json'
HERO_LIST = ROOT / 'data' / 'hero_list.json'
HERO_LIST_SEED = ROOT / 'resources' / 'builtin' / 'misc' / 'hero_list.json'
ROLE_POOLS = ROOT / 'data' / 'peak' / 'matchup_raw' / 'role_pools.json'
ROLE_POOLS_SEED = ROOT / 'resources' / 'builtin' / 'peak' / 'matchup_raw' / 'role_pools.json'

# 官方 roles / 巅峰千强 cid → 项目分路口径
LANE_BY_CODE = {'1': '对抗路', '2': '中路', '3': '发育路', '4': '打野', '5': '游走'}


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='hero-sync-', suffix='.json', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def official_names(offline: bool) -> dict[str, str]:
    """{heroId: 英雄名}；联网优先，失败回落到本地缓存。"""
    if not offline:
        try:
            import requests
            rows = requests.get(HERO_URL, timeout=25,
                                headers={'User-Agent': 'Mozilla/5.0'}).json()
            names = {str(row['ename']): str(row['cname']).strip()
                     for row in rows if str(row.get('ename', '')).isdigit() and row.get('cname')}
            if names:
                return names
        except Exception as exc:  # noqa: BLE001 - 联网失败就走缓存
            print(f'[hero-sync] 官方名录获取失败，改用本地缓存：{exc}', file=sys.stderr)
    return {str(k): str(v) for k, v in _read_json(HERO_LIST, {}).items()}


def lane_hints(names: dict[str, str]) -> dict[str, str]:
    """从巅峰千强分路池 / 官方 roles 取默认分路提示（只用于兜底展示）。"""
    hints = {}
    pools = _read_json(ROLE_POOLS if ROLE_POOLS.is_file() else ROLE_POOLS_SEED, {})
    for cid, rows in (pools or {}).items():
        lane = LANE_BY_CODE.get(str(cid))
        if not lane:
            continue
        for row in rows or []:
            if str(row.get('hero_id')) in names:
                hints[str(row['hero_id'])] = lane
    return hints


def fetch_icon(hid: str, name: str) -> str | None:
    """官方 jpg → PNG；失败返回 None（名字仍然可用，头像前端退回首字）。"""
    try:
        import requests
        from PIL import Image
        url = ICON_URL.format(hid=hid)
        raw = requests.get(url, timeout=25, headers={'User-Agent': 'Mozilla/5.0'}).content
        image = Image.open(io.BytesIO(raw)).convert('RGB')
        ICONS.mkdir(parents=True, exist_ok=True)
        target = ICONS / f'hero-{hid}.png'
        image.save(target, format='PNG')
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except Exception as exc:  # noqa: BLE001
        print(f'[hero-sync] {name}({hid}) 头像下载失败：{exc}', file=sys.stderr)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='实际写入；默认只报告差异')
    ap.add_argument('--offline', action='store_true', help='不联网，只按本地缓存补名字')
    ap.add_argument('--only', default='', help='只同步指定英雄（逗号分隔），例如 --only 刀锋宝贝')
    args = ap.parse_args(argv)
    only = {part.strip() for part in args.only.split(',') if part.strip()}

    names = official_names(args.offline)
    if not names:
        print('[hero-sync] 没有可用的英雄名录，退出。', file=sys.stderr)
        return 1
    catalog = _read_json(CATALOG, {'entries': []})
    entries = catalog.get('entries') or []
    have_ids = {str(e.get('id', '')).split('-')[-1] for e in entries if e.get('kind') == 'hero'}
    have_names = {e.get('name') for e in entries}
    tags_doc = _read_json(TAGS, {'schema': 'scrim-hero-tags-v1', 'heroes': {}})
    heroes = tags_doc.setdefault('heroes', {})
    dims = tags_doc.get('capabilityDims') or []
    hints = lane_hints(names)

    missing = [(hid, name) for hid, name in sorted(names.items(), key=lambda kv: int(kv[0]))
               if hid not in have_ids and name not in have_names]
    if only:
        missing = [(hid, name) for hid, name in missing if name in only]
    report = {'total': len(names), 'existingHeroes': len(have_ids),
              'missing': [name for _hid, name in missing], 'added': [], 'icons': [], 'applied': args.apply}
    if not missing:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    for hid, name in missing:
        if not args.apply:
            continue
        icon = ICONS / f'hero-{hid}.png'
        digest = None
        if icon.is_file():
            digest = hashlib.sha256(icon.read_bytes()).hexdigest()
        elif not args.offline:
            digest = fetch_icon(hid, name)
        entry = {'id': f'hero-{hid}', 'kind': 'hero', 'name': name,
                 'url': ICON_URL.format(hid=hid),
                 'icon': f'/catalog/icons/hero-{hid}.png' if digest else None}
        if digest:
            entry['sha256'] = digest
        entries.append(entry)
        heroes[name] = {
            'id': int(hid),
            'defaultLane': hints.get(hid, ''),
            'defaultType': '待分类',
            'compat': '',
            'lanes': {},
            'matrix': {dim: 0 for dim in dims},
            'note': '新英雄待赛训组在工作簿补打法类型与能力矩阵',
        }
        report['added'].append(name)
        if digest:
            report['icons'].append(f'hero-{hid}.png')

    if args.apply:
        try:
            catalog['updatedAt'] = __import__('datetime').datetime.now(
                __import__('datetime').timezone.utc).isoformat()
            _write_json(CATALOG, catalog)
            _write_json(TAGS, tags_doc)
            _write_json(HERO_LIST, names)
            if HERO_LIST_SEED.parent.is_dir():
                _write_json(HERO_LIST_SEED, names)
        except OSError as exc:
            print(f'[hero-sync] 写入失败：{exc}\n'
                  '安装到 Program Files 的程序目录通常不可写；请在源码目录执行本脚本，'
                  '然后重新打包发布。', file=sys.stderr)
            return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply:
        print('下一步：赛训组在英雄标签工作簿补这些英雄的打法类型 / 能力矩阵，'
              '然后跑 scripts/import_hero_labels.py 与 scripts/rebuild_hero_roles.py。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
