"""heroId → 英雄名称映射（官网 herolist，本地缓存 7 天）。

营地的 heroId 与官网 ename 同体系（152=王昭君、196=百里守约，实测对拍）。
首次调用需要联网下载；之后走本地缓存 data/hero_list.json。
"""
import json
import os
import time
import urllib.request
from pathlib import Path

from paths import data_root

ROOT = Path(__file__).resolve().parent
CACHE_PATH = Path(os.environ.get('HERO_LIST_FILE', data_root() / 'hero_list.json'))
TTL = 7 * 24 * 3600
URL = 'https://pvp.qq.com/web201605/js/herolist.json'
_CACHE = {'data': None, 'loadedAt': 0.0}


def _load(force: bool = False) -> dict:
    if not force and _CACHE['data'] is not None and time.time() - _CACHE['loadedAt'] < TTL:
        return _CACHE['data']
    if CACHE_PATH.is_file() and time.time() - CACHE_PATH.stat().st_mtime < TTL:
        try:
            _CACHE['data'] = {int(k): v for k, v in
                              json.loads(CACHE_PATH.read_text(encoding='utf-8')).items()}
            _CACHE['loadedAt'] = time.time()
            return _CACHE['data']
        except (OSError, ValueError):
            pass
    request = urllib.request.Request(URL, headers={'user-agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(request, timeout=15).read().decode('utf-8'))
    mapping = {int(item['ename']): str(item['cname'])
               for item in data if item.get('ename') is not None}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(mapping, ensure_ascii=False), encoding='utf-8')
    _CACHE.update({'data': mapping, 'loadedAt': time.time()})
    return mapping


def hero_name(hero_id, default=None):
    try:
        return _load().get(int(hero_id), default)
    except (TypeError, ValueError):
        return default


def hero_names(hero_ids):
    return [hero_name(hero_id, default=f'#{hero_id}') for hero_id in (hero_ids or [])]
