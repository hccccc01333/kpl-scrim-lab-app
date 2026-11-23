"""英雄榜外部口径：KPL 胜率 + 国服前十英雄战力分 + 大盘梯度（每日自动刷新）。

数据来源与口径
--------------
* KPL 胜率：本地缓存 data/kpl/bp_games.jsonl（官方赛程 BP 逐局记录，由
  kpl_bp.py / scripts/crawl_kpl_bp.py 抓取；每日自动任务也会增量补抓）。按
  「每局每队上场英雄」计一次出场，胜负取 winCamp，得到 games / wins /
  winRate(0–100)。这是本平台自算口径，不是 KPL 官方英雄榜。
* 国服前十英雄分：91m「战力排行」getRanking(aid=19, bid=0, cid=0)，
  每个英雄给出 fightPower = [全国第 1、10、50、100 名] 的英雄战力分。
  本榜取第 10 名（rank10）作为「国服第十英雄分」。
* 大盘梯度：91m「英雄详情」getHeroInfo 的 gradient 字段（T0 / T0.5 / T1 /
  T2 / T3 / T3.5 / T4.5，数值越小越强）与 allScore 综合强度分，口径是
  王者荣耀巅峰千强大盘，不是本队训练赛数据。逐英雄抓取，失败沿用旧值。
  每天自动爬取一次并落盘。

产物：data/facts/hero_external_stats.json
    {
      "schema": "hero-external-stats-v3",
      "updatedAt": "...", "windowStart": "...", "windowEnd": "...",
      "kpl": {"英雄名": {"games": N, "wins": N, "winRate": 53.2}},
      "top10": {"英雄名": {"rank1": 17699, "rank10": 16218, ...}},
      "big": {"英雄名": {"tier": 0.5, "score": 115.53, "winRate": 51.52}}
    }

用法：
    python hero_external_stats.py              # 重算 KPL + 抓国服前十 + 大盘梯度
    python hero_external_stats.py --kpl-only   # 只用本地对局重算，不联网
    python hero_external_stats.py --status     # 查看产物状态
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GAMES_PATH = ROOT / 'data' / 'kpl' / 'bp_games.jsonl'
OUT_PATH = ROOT / 'data' / 'facts' / 'hero_external_stats.json'
SCHEMA = 'hero-external-stats-v3'

API = 'https://api.91m.top/hero/app'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
    'Referer': 'https://pvp.91m.top/',
}
IS_DEMO = bool(os.environ.get('TRAINING_DEMO_ROOT'))

_load_cache: tuple[tuple, dict] | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def normalize_hero(name) -> str:
    """91m 用 `元流之子_辅助`，营地/回放用 `元流之子(辅助)`，统一成后者。"""
    text = str(name or '').strip()
    if '_' in text:
        base, _, form = text.partition('_')
        return f'{base}({form})'
    return text


def build_kpl() -> tuple[dict, str, str]:
    """从本地 KPL 逐局缓存聚合每英雄胜率。返回 (stats, 起始日期, 结束日期)。"""
    stats: dict[str, dict] = {}
    first = last = ''
    if not GAMES_PATH.exists():
        return stats, first, last
    with GAMES_PATH.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            day = str(row.get('date') or '')[:10]
            if day:
                first = min(first, day) if first else day
                last = max(last, day) if last else day
            winner = str(row.get('winCamp') or '')
            if winner not in ('1', '2'):
                continue
            picks = row.get('picks') or {}
            for camp in ('1', '2'):
                seen: set[str] = set()
                for raw in picks.get(camp) or []:
                    hero = normalize_hero(raw)
                    if not hero or hero in seen:
                        continue
                    seen.add(hero)
                    item = stats.setdefault(hero, {'games': 0, 'wins': 0})
                    item['games'] += 1
                    if camp == winner:
                        item['wins'] += 1
    for item in stats.values():
        games = item['games']
        item['winRate'] = round(item['wins'] / games * 100, 1) if games else None
    return stats, first, last


def fetch_top10() -> dict[str, dict]:
    """91m「战力排行」getRanking(aid=19)：每英雄国服 #1/#10/#50/#100 战力分。"""
    if IS_DEMO:
        return {}
    payload = None
    for attempt in range(3):
        try:
            response = requests.get(API, params={
                'gameType': 'wzry', 'type': 'getRanking',
                'aid': 19, 'bid': 0, 'cid': 0, 'did': 0, 'eid': 'b',
            }, headers=HEADERS, timeout=25)
            response.raise_for_status()
            payload = response.json()
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                print(f'[hero-stats] 国服战力分抓取失败：{str(exc)[:120]}', flush=True)
                return {}
            time.sleep(1.5 * (attempt + 1))
    rows = (((payload or {}).get('data') or {}).get('result') or {}).get('rows') or []
    out: dict[str, dict] = {}
    for row in rows:
        name = normalize_hero(row.get('name'))
        scores = row.get('fightPower') or []
        if not name or not isinstance(scores, (list, tuple)) or len(scores) < 2:
            continue
        values = {}
        for key, value in zip(('rank1', 'rank10', 'rank50', 'rank100'), scores):
            if isinstance(value, (int, float)) and value > 0:
                values[key] = round(float(value))
        if 'rank10' in values:
            out[name] = values
    return out


def fetch_big() -> dict[str, dict]:
    """91m 英雄详情的 gradient（大盘梯度）+ allScore 综合强度分。"""
    if IS_DEMO:
        return {}
    try:
        listing = requests.get(API, params={
            'gameType': 'wzry', 'type': 'getRanking',
            'aid': 0, 'bid': 0, 'cid': 0, 'did': 0, 'eid': 'b',
        }, headers=HEADERS, timeout=25)
        listing.raise_for_status()
        rows = (((listing.json().get('data') or {}).get('result') or {}).get('rows')) or []
    except Exception as exc:  # noqa: BLE001
        print(f'[hero-stats] 大盘梯度名单读取失败：{str(exc)[:120]}', flush=True)
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        hero_id = row.get('id')
        name = normalize_hero(row.get('name'))
        if not hero_id or not name:
            continue
        try:
            response = requests.get(API, params={
                'gameType': 'wzry', 'type': 'getHeroInfo', 'id': hero_id,
            }, headers=HEADERS, timeout=10)
            response.raise_for_status()
            info = ((response.json().get('data') or {}).get('heroInfo')) or {}
        except Exception:  # noqa: BLE001
            continue
        tier = info.get('gradient')
        if not isinstance(tier, (int, float)):
            continue
        score = row.get('allScore')
        win = row.get('allWinRate')
        out[name] = {
            'tier': float(tier),
            'score': round(float(score), 2) if isinstance(score, (int, float)) else None,
            'winRate': round(float(win), 2) if isinstance(win, (int, float)) else None,
        }
        time.sleep(0.03)
    return out


def build(kpl_only: bool = False, top_only: bool = False) -> dict:
    previous = load()
    if top_only:
        kpl = previous.get('kpl') or {}
        first = previous.get('windowStart') or ''
        last = previous.get('windowEnd') or ''
    else:
        kpl, first, last = build_kpl()
    top10 = {} if kpl_only else fetch_top10()
    if not kpl_only and not top10:
        top10 = previous.get('top10') or {}
    big = {} if kpl_only else fetch_big()
    if not kpl_only and not big:
        big = previous.get('big') or {}
    result = {
        'schema': SCHEMA,
        'updatedAt': _now_iso(),
        'windowStart': first,
        'windowEnd': last,
        'kpl': kpl,
        'top10': top10,
        'big': big,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(OUT_PATH)
    return result


def load() -> dict:
    """按 mtime + size 缓存读取；文件不存在或损坏返回空字典。"""
    global _load_cache
    try:
        stat = OUT_PATH.stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    if _load_cache and _load_cache[0] == key:
        return _load_cache[1]
    try:
        data = json.loads(OUT_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if data.get('schema') != SCHEMA:
        return {}
    _load_cache = (key, data)
    return data


def hero_fields(name: str) -> dict:
    """给 API 行补外部口径字段；没数据就不写，前端保持「—」。"""
    data = load()
    hero = normalize_hero(name)
    out: dict = {}
    kpl = (data.get('kpl') or {}).get(hero)
    if kpl and isinstance(kpl.get('winRate'), (int, float)):
        out['kplWinRate'] = kpl['winRate']
        out['kplGames'] = kpl.get('games')
    top = (data.get('top10') or {}).get(hero)
    if top and isinstance(top.get('rank10'), (int, float)):
        out['peak10'] = top['rank10']          # 前端原字段名，现为国服第十英雄战力分
        out['top1'] = top.get('rank1')
        out['top50'] = top.get('rank50')
        out['top100'] = top.get('rank100')
    big = (data.get('big') or {}).get(hero)
    if big and isinstance(big.get('tier'), (int, float)):
        out['bigTier'] = big['tier']
        out['bigScore'] = big.get('score')
        out['bigWinRate'] = big.get('winRate')
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='英雄榜 KPL / 国服前十战力分 / 大盘梯度统计')
    parser.add_argument('--kpl-only', action='store_true', help='只按本地 KPL 对局重算，不联网')
    parser.add_argument('--top-only', action='store_true', help='只抓国服前十战力分，KPL 沿用上次结果')
    parser.add_argument('--status', action='store_true', help='查看当前产物状态')
    args = parser.parse_args()
    if args.status:
        data = load()
        print(json.dumps({
            'exists': bool(data), 'updatedAt': data.get('updatedAt'),
            'window': [data.get('windowStart'), data.get('windowEnd')],
            'kplHeroes': len(data.get('kpl') or {}),
            'top10Heroes': len(data.get('top10') or {}),
            'bigHeroes': len(data.get('big') or {}),
            'path': str(OUT_PATH),
        }, ensure_ascii=False))
        return 0
    result = build(kpl_only=args.kpl_only, top_only=args.top_only)
    print(f"[hero-stats] 写入 {OUT_PATH.relative_to(ROOT)}："
          f"KPL {len(result['kpl'])} 英雄，国服前十战力分 {len(result['top10'])} 英雄，"
          f"大盘梯度 {len(result['big'])} 英雄，更新于 {result['updatedAt']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
