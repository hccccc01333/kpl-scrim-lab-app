"""巅峰千强（91m 大盘）自动爬取与 lane_matchups.json 重建。

对位压制的外部事实来源是 api.91m.top（苏苏的荣耀助手）的公开接口：

* ``getRanking``        —— 英雄榜；``cid=1..5`` 给出对抗路/中路/发育路/打野/游走的英雄池
* ``getHeroChartsLog``  —— 每个英雄逐日 胜率/出场/禁用（巅峰千强等分段，2019-09 起全量）
* ``getExplorer``       —— 同分路两两英雄的对位总局数与蓝方胜率（公开探索器接口）

此前这条链路依赖外部手工爬取，``lane_matchups.json`` 只能等
手动重建；现在整条链路搬进本项目并自动化：

    服务启动 / 每日定时 → 刷新英雄日线 → 重建 hero_daily.parquet →
    重爬对位矩阵（分片落盘） → 重建 data/facts/lane_matchups.json

数据落在 ``data/peak/``；每一轮对位爬取写一个带时间戳的 jsonl 分片，重建时每个
**有序对位**取时间戳最新的一条（早期基线当兜底，新一轮只覆盖爬到的对位）。这样
一轮中断不会污染结果，已爬到的对位立刻生效。

口径与 ``scripts/build_bp_facts.py`` 完全一致（同一组纯函数），只是数据来源换成
本项目自抓。

用法：
    python peak_crawl.py --status                 # 查看爬取状态
    python peak_crawl.py --charts --build-daily   # 只刷英雄日线
    python peak_crawl.py --matchups --limit 50    # 试爬 50 个对位
    python peak_crawl.py --all                    # 一轮完整刷新（bat 用这个）
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bp_facts import (BRACKET, MIN_PAIR_N, MIN_PICK_RATE,  # noqa: E402
                                    WIN_WINDOW_DAYS, _load_hero_daily,
                                    build_lane_rows, build_ladder_doc)
from hero_catalog import hero_name  # noqa: E402  heroId → 英雄名（本地缓存，离线可用）
import hero_external_stats  # noqa: E402  英雄榜 KPL 胜率 / 国服前十战力分

API = 'https://api.91m.top/hero/app'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
    'Referer': 'https://pvp.91m.top/',
}
ROLE_BY_CID = {1: '对抗路', 2: '中路', 3: '发育路', 4: '打野', 5: '游走'}
POSITION_BY_CID = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

PEAK_DIR = ROOT / 'data' / 'peak'
CHARTS_DIR = PEAK_DIR / 'charts'
DAILY_PARQUET = PEAK_DIR / 'hero_daily.parquet'
MATCHUP_DIR = PEAK_DIR / 'matchup_raw'
FACTS_PATH = ROOT / 'data' / 'facts' / 'lane_matchups.json'
STATE_PATH = PEAK_DIR / 'state.json'

# 演示数据包环境不联网爬取；与 v3/serve.py 的 IS_DEMO 同一判定
IS_DEMO = bool(os.environ.get('TRAINING_DEMO_ROOT'))
WORKERS = 4            # 对位爬取并发数
PAIR_DELAY = 0.12      # 每请求基础间隔（秒），加随机抖动防限流
CHART_SLEEP = 0.25     # 英雄日线逐个请求的间隔

_state_lock = threading.Lock()
_state: dict = {
    'running': False, 'phase': '', 'reason': '',
    'chartsDone': 0, 'chartsTotal': 0,
    'pairsDone': 0, 'pairsTotal': 0,
    'startedAt': '', 'finishedAt': '', 'lastError': '',
    'windowEnd': '', 'pairs': 0,
}
_thread_started = False


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _save_state() -> None:
    try:
        PEAK_DIR.mkdir(parents=True, exist_ok=True)
        with _state_lock:
            STATE_PATH.write_text(json.dumps(_state, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def status() -> dict:
    """爬取状态快照（API / 前端展示用）。文件不在时给静默默认值。"""
    with _state_lock:
        snap = dict(_state)
    if not snap['windowEnd'] and FACTS_PATH.exists():
        try:
            facts = json.loads(FACTS_PATH.read_text(encoding='utf-8'))
            snap['windowEnd'] = str(facts.get('windowEnd') or '')
            snap['pairs'] = len(facts.get('pairs') or [])
        except (OSError, ValueError):
            pass
    snap['enabled'] = _auto_enabled()
    snap['stale'] = not _is_fresh()
    return snap


def _is_fresh() -> bool:
    """今天已经完整刷过一轮（或试过但失败）就算新鲜。

    91m 的日线是对源站隔天发布的，「今日」口径指今天刷新过、拿到源站最新数据，
    不要求源站已有今天的一行；同一天不反复重爬。
    """
    try:
        facts = json.loads(FACTS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not facts.get('pairs'):
        return False
    # 英雄榜外部口径（KPL 胜率 + 国服前十战力分）也要每天重算一次
    try:
        if date.fromtimestamp(hero_external_stats.OUT_PATH.stat().st_mtime).isoformat() != date.today().isoformat():
            return False
    except OSError:
        return False
    today = date.today().isoformat()
    with _state_lock:
        state = dict(_state)
    if state.get('lastError') and str(state.get('startedAt') or '')[:10] == today:
        return True  # 今天试过但失败：不无限重试，明天再说
    return str(state.get('finishedAt') or '')[:10] == today


def _auto_enabled() -> bool:
    if IS_DEMO:
        return False
    if os.environ.get('PEAK_CRAWL') == '0':
        return False
    return os.environ.get('PEAK_AUTO_CRAWL') == '1'


# ---------------------------------------------------------------------------
# 91m 公开接口
# ---------------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _get(session: requests.Session, params: dict, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            resp = session.get(API, params={'gameType': 'wzry', **params},
                               headers=HEADERS, timeout=45)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f'GET {params} 失败：{last}')


def fetch_role_pools(session: requests.Session, cids=(1, 2, 3, 4, 5)) -> dict[int, list[dict]]:
    """分路英雄池：getRanking cid=1..5，每路去重后的英雄 id + 名字。"""
    pools: dict[int, list[dict]] = {}
    for cid in cids:
        payload = _get(session, {'type': 'getRanking', 'aid': 0, 'bid': 0,
                                 'cid': cid, 'did': 0, 'eid': 'b'})
        rows = ((payload.get('data') or {}).get('result') or {}).get('rows') or []
        seen: set[int] = set()
        pool = []
        for row in rows:
            hid = row.get('id')
            if hid is None or int(hid) in seen:
                continue
            seen.add(int(hid))
            pool.append({'hero_id': int(hid), 'hero_name': row.get('name') or str(hid)})
        pools[cid] = pool
        time.sleep(CHART_SLEEP)
    return pools


def fetch_chart(session: requests.Session, hero_id: int) -> dict | None:
    """getHeroChartsLog：单个英雄逐日数据（gzip 缓存到 data/peak/charts/）。"""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / f'hero_{hero_id}_charts.json.gz'
    try:
        payload = _get(session, {'type': 'getHeroChartsLog', 'id': hero_id})
    except Exception as exc:  # noqa: BLE001
        # 单个英雄失败不阻塞整轮：保留旧缓存（哪怕是旧的），下轮再补
        print(f'[peak] 英雄 {hero_id} 日线抓取失败：{str(exc)[:120]}', flush=True)
        return {'_stale': True} if path.exists() else None
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode('utf-8')))
    tmp.replace(path)
    return payload


def chart_rows(hero_id: int, hero_name: str, payload: dict):
    """getHeroChartsLog → 逐日长表行（bracket × 胜率/出场/禁用）。"""
    data = payload.get('data') or {}
    rows = ((data.get('result') or {}).get('rows')) or []
    for row in rows:
        day = str(row.get('日期', ''))[:10]
        if not day:
            continue
        heat = row.get('热度')
        for bracket in ('巅峰千强', '赛事', '顶端排位', '1350+', '全分段'):
            win = row.get(f'{bracket}:胜率')
            pick = row.get(f'{bracket}:出场')
            ban = row.get(f'{bracket}:禁用')
            if win is None and pick is None and ban is None:
                continue
            yield {'date': day, 'hero_id': hero_id, 'hero_name': hero_name,
                   'bracket': bracket, 'win_rate': win, 'pick_rate': pick,
                   'ban_rate': ban, 'heat': heat}


def build_daily_parquet() -> str:
    """data/peak/charts/*.gz → data/peak/hero_daily.parquet（逐英雄流式写，控制内存）。"""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ('date', pa.date32()), ('hero_id', pa.int32()), ('hero_name', pa.string()),
        ('bracket', pa.string()), ('win_rate', pa.float32()), ('pick_rate', pa.float32()),
        ('ban_rate', pa.float32()), ('heat', pa.float32()),
    ])
    DAILY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    tmp = DAILY_PARQUET.with_suffix('.parquet.tmp')
    writer = pq.ParquetWriter(tmp, schema, compression='zstd')
    latest = ''
    files = sorted(CHARTS_DIR.glob('hero_*_charts.json.gz'))
    for path in files:
        hero_id = int(path.stem.split('_')[1])
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
        except (OSError, ValueError):
            continue
        # 英雄名要在生成行之前就定好：chart_rows 把 hero_name 写进每一行，
        # 以前先传空串、事后再读 rows[-1]['hero_name']，读到的还是空串 ——
        # 135 个英雄的日线全变成无名行，对位表随后被折叠成一条空名记录（2026-11-14 修）。
        name = hero_name(hero_id) or str(hero_id)
        rows = list(chart_rows(hero_id, name, payload))
        if rows:
            frame = pd.DataFrame(rows)
            frame['date'] = pd.to_datetime(frame['date'], errors='coerce').dt.date
            table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
            writer.write_table(table)
            day = str(rows[-1]['date'])
            latest = max(latest, day)
    writer.close()
    tmp.replace(DAILY_PARQUET)
    return latest


# ---------------------------------------------------------------------------
# 对位矩阵爬取（每轮一个带时间戳的分片文件）
# ---------------------------------------------------------------------------
def _fetch_pair(session: requests.Session, cid: int, blue_id: int, red_id: int,
                retries: int = 3) -> dict:
    position = POSITION_BY_CID[cid]
    payload = {'blueCamp': [{'id': blue_id, 'position': position}],
               'redCamp': [{'id': red_id, 'position': position}]}
    last = None
    for attempt in range(retries):
        try:
            resp = session.post(API, params={'type': 'getExplorer', 'gameType': 'wzry'},
                                data={'extraData': json.dumps(payload, ensure_ascii=False)},
                                headers=HEADERS, timeout=45)
            resp.raise_for_status()
            doc = resp.json()
            api_status = doc.get('status') or {}
            data = doc.get('data')
            if api_status.get('code') != 200 or not isinstance(data, dict) or 'base' not in data:
                raise RuntimeError(f"api code={api_status.get('code')}")
            base = data['base']
            return {'cid': cid, 'position': position, 'blue_id': blue_id, 'red_id': red_id,
                    'n': int(base.get('allPickTimes') or 0),
                    'blue_wins': int(base.get('campWinTimes_1') or 0),
                    'red_wins': int(base.get('campWinTimes_2') or 0),
                    'blue_win_rate': base.get('campWinRate_1'),
                    'red_win_rate': base.get('campWinRate_2'),
                    'status': 'ok'}
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (attempt + 1) + random.random() * 0.4)
    return {'cid': cid, 'position': position, 'blue_id': blue_id, 'red_id': red_id,
            'n': 0, 'status': 'error', 'error': str(last)[:200]}


def crawl_matchups(max_requests: int = 0, log=print) -> dict:
    """全量重爬对位矩阵，写进本轮专属分片 ``matchups_<run>.jsonl``。

    分片内已出现的对位（同一 run_id）不重复请求——服务重启后接着本轮文件续爬。
    """
    session = _session()
    pools = fetch_role_pools(session)
    MATCHUP_DIR.mkdir(parents=True, exist_ok=True)
    (MATCHUP_DIR / 'role_pools.json').write_text(
        json.dumps(pools, ensure_ascii=False), encoding='utf-8')

    tasks: list[tuple[int, int, int]] = []
    for cid, pool in pools.items():
        ids = [int(h['hero_id']) for h in pool]
        for a in ids:
            for b in ids:
                if a != b:
                    tasks.append((cid, a, b))
    run_id = datetime.now().strftime('%Y%m%d-%H%M')
    shard = MATCHUP_DIR / f'matchups_{run_id}.jsonl'
    done: set[str] = set()
    if shard.exists():
        with shard.open('r', encoding='utf-8') as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('status') == 'ok':
                    done.add(f"{row['cid']}:{row['blue_id']}:{row['red_id']}")
    pending = [t for t in tasks if f'{t[0]}:{t[1]}:{t[2]}' not in done]
    if max_requests:
        pending = pending[:max_requests]
    total = len(pending)
    log(f'[peak] 对位矩阵：任务 {len(tasks)} · 本轮待爬 {total}（{shard.name}）')

    counters = {'ok': 0, 'error': 0}
    started = time.time()
    lock = threading.Lock()
    with shard.open('a', encoding='utf-8', buffering=1) as fh:
        def run(task):
            cid, a, b = task
            time.sleep(PAIR_DELAY + random.random() * PAIR_DELAY)
            return _fetch_pair(session, cid, a, b)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(run, t) for t in pending]
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                row['ts'] = _now_iso()
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
                with lock:
                    counters['ok' if row['status'] == 'ok' else 'error'] += 1
                    with _state_lock:
                        _state['pairsDone'] += 1
                if i % 200 == 0 or i == total:
                    rate = i / max(time.time() - started, 1e-6)
                    log(f'[peak] 对位 {i}/{total} ok={counters["ok"]} err={counters["error"]} '
                        f'{rate:.1f} req/s eta={((total - i) / max(rate, 1e-6)) / 60:.0f}min')
    return {'shard': str(shard), 'total': total, **counters}


def _latest_matchup_rows(log=print) -> list[dict]:
    """所有分片 → 每个**有序对位**取 ts 最新的一行（老基线兜底，新一轮覆盖）。"""
    best: dict[str, dict] = {}
    for path in sorted(MATCHUP_DIR.glob('matchups_*.jsonl')):
        with path.open('r', encoding='utf-8') as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('status') != 'ok':
                    continue
                key = f"{row.get('cid')}:{row.get('blue_id')}:{row.get('red_id')}"
                held = best.get(key)
                if held is None or str(row.get('ts') or '') >= str(held.get('ts') or ''):
                    best[key] = row
    log(f'[peak] 对位基线：{len(best)} 条有序对位（取每对最新）')
    return list(best.values())


def rebuild_facts(log=print) -> dict:
    """hero_daily.parquet + 最新对位行 → data/facts/lane_matchups.json。"""
    if not DAILY_PARQUET.exists():
        raise RuntimeError('hero_daily.parquet 不存在，先跑 --charts --build-daily')
    from scripts.build_bp_facts import _role_pools  # noqa: E402  （分路池 → T1–T4 档位）
    hero_stats, window_end = _load_hero_daily(DAILY_PARQUET, date.today())
    rows = build_lane_rows(_latest_matchup_rows(log), hero_stats)
    ladder = build_ladder_doc(rows, hero_stats, window_end,
                              _role_pools(MATCHUP_DIR / 'role_pools.json'))
    FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FACTS_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(ladder, ensure_ascii=False), encoding='utf-8')
    tmp.replace(FACTS_PATH)
    tiers = sum(1 for row in ladder['heroes'].values() if row.get('tier'))
    log(f'[peak] lane_matchups.json 重建：{len(rows)} 条对位 · 窗口 {window_end} · '
        f'{tiers} 个英雄有档位')
    with _state_lock:
        _state['windowEnd'] = str(window_end)
        _state['pairs'] = len(rows)
    return {'pairs': len(rows), 'windowEnd': str(window_end), 'tiers': tiers}


# ---------------------------------------------------------------------------
# 一轮完整刷新 + 自动定时
# ---------------------------------------------------------------------------
def refresh(reason: str = 'manual', max_requests: int = 0, log=print) -> dict:
    """charts → hero_daily → 对位矩阵 → lane_matchups.json，全程单飞（幂等）。"""
    with _state_lock:
        if _state['running']:
            return {'ok': False, 'skipped': '已有刷新在跑'}
        _state.update({'running': True, 'phase': 'charts', 'reason': reason,
                       'lastError': '', 'startedAt': _now_iso(), 'finishedAt': '',
                       'chartsDone': 0, 'chartsTotal': 0,
                       'pairsDone': 0, 'pairsTotal': 0})
    _save_state()
    result: dict = {'ok': True, 'reason': reason}
    try:
        session = _session()
        pools = fetch_role_pools(session)
        heroes: dict[int, str] = {}
        for pool in pools.values():
            for h in pool:
                heroes[int(h['hero_id'])] = str(h['hero_name'])
        with _state_lock:
            _state['chartsTotal'] = len(heroes)
        failed = 0
        for index, (hero_id, name) in enumerate(sorted(heroes.items()), 1):
            payload = fetch_chart(session, hero_id)
            if payload is None:
                failed += 1
            with _state_lock:
                _state['chartsDone'] = index
                _state['phase'] = 'charts'
            if index % 30 == 0:
                log(f'[peak] 日线 {index}/{len(heroes)}（失败 {failed}）')
            time.sleep(CHART_SLEEP)
        result['charts'] = {'total': len(heroes), 'failed': failed}

        with _state_lock:
            _state['phase'] = 'daily'
        result['dailyWindow'] = build_daily_parquet()

        with _state_lock:
            _state['phase'] = 'matchups'
        result['matchups'] = crawl_matchups(max_requests=max_requests, log=log)

        with _state_lock:
            _state['phase'] = 'facts'
        result['facts'] = rebuild_facts(log=log)

        with _state_lock:
            _state['phase'] = 'kpl'
        # KPL 增量抓取：官方赛程 BP，按 battleId 去重；失败只记日志，不拖垮整轮。
        if not IS_DEMO and os.environ.get('KPL_AUTO_CRAWL', '1') != '0':
            try:
                import kpl_bp  # noqa: PLC0415  延迟导入，避免 demo / 未安装依赖时影响巅峰链路
                kpl_report = kpl_bp.run_crawl(limit=120, log=log)
                result['kplCrawl'] = {
                    'added': (kpl_report.get('crawl') or {}).get('added', 0),
                    'skipped': (kpl_report.get('crawl') or {}).get('skippedExisting', 0),
                }
                log(f"[peak] KPL 增量：新增 {result['kplCrawl']['added']} 局")
            except Exception as exc:  # noqa: BLE001
                result['kplCrawl'] = {'error': str(exc)[:200]}
                log(f'[peak] KPL 增量抓取跳过：{str(exc)[:120]}')

        with _state_lock:
            _state['phase'] = 'hero-stats'
        stats = hero_external_stats.build()
        result['heroStats'] = {
            'kpl': len(stats.get('kpl') or {}),
            'top10': len(stats.get('top10') or {}),
            'big': len(stats.get('big') or {}),
            'updatedAt': stats.get('updatedAt'),
        }
        log(f"[peak] 英雄榜口径：KPL {result['heroStats']['kpl']} 英雄 / "
            f"国服前十战力分 {result['heroStats']['top10']} 英雄 / "
            f"大盘梯度 {result['heroStats']['big']} 英雄")
    except Exception as exc:  # noqa: BLE001
        result['ok'] = False
        result['error'] = str(exc)[:300]
        with _state_lock:
            _state['lastError'] = str(exc)[:300]
        log(f'[peak] 刷新失败：{exc}')
    finally:
        with _state_lock:
            _state['running'] = False
            _state['phase'] = ''
            _state['finishedAt'] = _now_iso()
        _save_state()
        log('[peak] 刷新结束：' + json.dumps(
            {k: v for k, v in result.items() if k != 'reason'}, ensure_ascii=False)[:400])
    return result


def auto_loop(interval_minutes: int = 30, log=print) -> None:
    """守护线程主体：今天还没刷过一轮就刷，之后每 interval 分钟查一次（一天最多一轮完整刷新）。"""
    while True:
        try:
            if not _is_fresh():
                log('[peak] lane_matchups 不是今天的，开始自动刷新')
                refresh(reason='auto', log=log)
        except Exception as exc:  # noqa: BLE001
            log(f'[peak] 自动刷新异常：{exc}')
        time.sleep(max(5, interval_minutes) * 60)


def start_auto(log=print) -> bool:
    """进程内启动自动刷新线程（重复调用只起一次）。"""
    global _thread_started
    if not _auto_enabled():
        return False
    with _state_lock:
        if _thread_started:
            return False
        _thread_started = True
    thread = threading.Thread(target=auto_loop, kwargs={'log': log},
                              name='peak-crawl', daemon=True)
    thread.start()
    log('[peak] 自动刷新线程已启动（每日 windowEnd 变化后触发）')
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='巅峰千强大盘自动爬取')
    ap.add_argument('--all', action='store_true', help='一轮完整刷新（日线 + 对位 + 重建）')
    ap.add_argument('--charts', action='store_true', help='刷新英雄日线缓存')
    ap.add_argument('--build-daily', action='store_true', help='从缓存重建 hero_daily.parquet')
    ap.add_argument('--matchups', action='store_true', help='爬对位矩阵（本轮分片）')
    ap.add_argument('--build', action='store_true', help='重建 lane_matchups.json')
    ap.add_argument('--hero-stats', action='store_true', help='重算英雄榜 KPL 胜率 + 抓国服前十战力分')
    ap.add_argument('--limit', type=int, default=0, help='本次最多爬多少个对位（试跑用）')
    ap.add_argument('--status', action='store_true', help='只看状态')
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0

    def log(text):
        print(text, flush=True)

    if args.all:
        result = refresh(reason='cli', max_requests=args.limit, log=log)
        return 0 if result.get('ok') else 1
    ok = True
    if args.charts:
        session = _session()
        pools = fetch_role_pools(session)
        heroes = sorted({int(h['hero_id']) for pool in pools.values() for h in pool})
        failed = 0
        for index, hero_id in enumerate(heroes, 1):
            if fetch_chart(session, hero_id) is None:
                failed += 1
            if index % 30 == 0:
                log(f'[peak] 日线 {index}/{len(heroes)}')
            time.sleep(CHART_SLEEP)
        log(f'[peak] 日线完成：{len(heroes) - failed}/{len(heroes)}')
        ok = ok and failed < len(heroes)
    if args.build_daily:
        log(f'[peak] hero_daily 窗口：{build_daily_parquet()}')
    if args.matchups:
        crawl_matchups(max_requests=args.limit, log=log)
    if args.build:
        rebuild_facts(log=log)
    if args.hero_stats:
        stats = hero_external_stats.build()
        log(f"[peak] 英雄榜口径：KPL {len(stats.get('kpl') or {})} 英雄 / "
            f"国服前十战力分 {len(stats.get('top10') or {})} 英雄 / "
            f"大盘梯度 {len(stats.get('big') or {})} 英雄")
    if not (args.charts or args.build_daily or args.matchups or args.build or args.hero_stats):
        ap.print_help()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
