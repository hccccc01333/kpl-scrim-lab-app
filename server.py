"""Loopback-only training review app; SQLite holds records and original images."""
import base64
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib import parse as url_parse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from analysis_api import create_analysis_router
from workbench_api import create_workbench_router
from depth_api import create_depth_router
from match_review import create_review_router
from studio_api import create_studio_router
from update_api import create_update_router
from paths import DATA_DIR, data_root
from version import VERSION, RELEASE_DATE, RELEASE_NAME

import media_tools
import focus as focus_module
import camp_replay
from camp_time import camp_times
from collection_contract import PAGE_NAMES, PAGE_TYPES, validate_sheet
import channel_store
import mimo_ocr
import ocr_jobs
import official_economy
import postgame_mimo
import recording_store
import video_mimo
import video_ocr
from domain import summarize, validate_match
from ocr import recognize
from postgame_ocr import OCR_VERSION as POSTGAME_OCR_VERSION
from postgame_ocr import merge_pages as merge_postgame_pages
from postgame_ocr import recognize as recognize_postgame
from postgame_analysis import analyze_group
from sheet_import import apply_profile, infer_profile, read_workbook
from runtime_data import MAX_BYTES as MAX_RUNTIME_BYTES, RuntimeDataError, analyze_jsonl
from vision import OCR_VERSION, catalog, crop_box, descriptor, prepare_image

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('TRAINING_DB', DATA_DIR / 'training.sqlite3'))
MATCHES_DIR = Path(os.environ.get('ANALYSIS_MATCHES', DATA_DIR / 'matches'))
IMPORTS_DIR = Path(os.environ.get('ANALYSIS_IMPORTS', DATA_DIR / 'imports'))
OFFICIAL_DIR = Path(os.environ.get('ANALYSIS_OFFICIAL', DATA_DIR / 'official_replays'))
BUILDS_DIR = Path(os.environ.get('ANALYSIS_BUILDS') or (DATA_DIR / 'builds'))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_IMAGE = 12 * 1024 * 1024

# The default remains loopback-only.  Set TRAINING_ALLOW_REMOTE=1 only when
# the workbench is deliberately exposed on a trusted LAN / container network.
_ALLOW_REMOTE = os.environ.get('TRAINING_ALLOW_REMOTE', '').strip().lower() in (
    '1', 'true', 'yes', 'on')
_ALLOWED_HOSTS = {
    item.strip().lower()
    for item in os.environ.get(
        'TRAINING_ALLOWED_HOSTS',
        '127.0.0.1,localhost,::1'
    ).split(',')
    if item.strip()
}


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, ocr TEXT);
        CREATE TABLE IF NOT EXISTS postgame_images (id TEXT PRIMARY KEY, result TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_files (id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, uploaded_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, match_id TEXT, saved_at REAL, body TEXT);
        CREATE TABLE IF NOT EXISTS replay_files (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS replays (id TEXT PRIMARY KEY, abc_file_id TEXT NOT NULL, ope_file_id TEXT, body TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS replay_checkpoints (replay_id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS focus_items (id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps({'teamName': '我的训练队', 'roster': []}, ensure_ascii=False),))


init_db()
app = FastAPI(title='训练赛分析工作台', docs_url=None, redoc_url=None)
# V3 的路由模块在 _mount_v3() 里加载；中间件用它刷新分析快照缓存。
V3_MODULE = None
app.include_router(create_analysis_router(DB_PATH, MATCHES_DIR, IMPORTS_DIR, OFFICIAL_DIR))
app.include_router(create_workbench_router(OFFICIAL_DIR, DATA_DIR / 'camp_details',
                                          DATA_DIR, DB_PATH))
app.include_router(create_depth_router(ROOT, DB_PATH))
app.include_router(create_studio_router(DB_PATH, MATCHES_DIR, IMPORTS_DIR))
app.include_router(create_review_router(MATCHES_DIR, OFFICIAL_DIR, BUILDS_DIR, ROOT))
app.include_router(create_update_router(ROOT, VERSION))


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0].strip('[]').lower()
    if not _ALLOW_REMOTE and host not in _ALLOWED_HOSTS:
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method != 'GET' and origin and origin not in (f'http://{request.headers.get("host")}',):
        return JSONResponse({'detail': '来源不匹配，请从本地工作台操作'}, status_code=403)
    response = await call_next(request)
    # V3 与分析快照：写操作成功后让缓存失效，下次读取重新构建。
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and response.status_code < 400:
        if V3_MODULE is not None:
            V3_MODULE.invalidate_snapshot()
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith(('/assets', '/static', '/api')) or request.url.path in ('/', '/analysis'):
        # 本机工作台经常直接替换前端文件；每次协商校验，避免浏览器用旧资源
        response.headers['Cache-Control'] = 'no-store'
    return response


def settings(c):
    return json.loads(c.execute('SELECT body FROM settings WHERE id=1').fetchone()[0])


def records(c):
    return [json.loads(row[0]) for row in c.execute('SELECT body FROM matches')]


def validate_settings(value):
    if not isinstance(value, dict) or not isinstance(value.get('teamName'), str) or not value['teamName'].strip():
        raise ValueError('请填写战队名称')
    roster = value.get('roster')
    if not isinstance(roster, list) or len(roster) > 40:
        raise ValueError('队员名单最多 40 人')
    ids = set()
    for p in roster:
        if not isinstance(p, dict) or not isinstance(p.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', p['id']) or p['id'] in ids:
            raise ValueError('队员 ID 缺失或重复')
        if not isinstance(p.get('name'), str) or not p['name'].strip() or len(p['name']) > 50:
            raise ValueError('请填写有效的选手名（职业 ID 或真名）')
        if p.get('realName') is not None and (not isinstance(p['realName'], str) or len(p['realName']) > 50):
            raise ValueError('选手真名无效')
        tags = p.get('tags', [])
        if not isinstance(tags, list) or len(tags) > 8 or any(
                not isinstance(tag, str) or not tag.strip() or len(tag) > 12 for tag in tags):
            raise ValueError('选手标签无效（最多 8 个，每个 12 字以内）')
        p['tags'] = [tag.strip() for tag in tags if tag.strip()]
        ids.add(p['id'])
        if p.get('position', '') not in ['', '对抗路', '打野', '中路', '发育路', '游走']:
            raise ValueError('队员默认分路无效')
        if p.get('team') is not None and (not isinstance(p['team'], str) or len(p['team']) > 50):
            raise ValueError('所属战队无效')
        camp_user_id = str(p.get('campUserId') or '').strip()
        if camp_user_id and not re.fullmatch(r'\d{5,15}', camp_user_id):
            raise ValueError('营地 ID 需为 5–15 位数字')
        p['campUserId'] = camp_user_id
        p.pop('archived', None)  # 名单移除就是硬删除，不再保留软删除标记
    teams = value.get('teams', [])
    if not isinstance(teams, list) or len(teams) > 60:
        raise ValueError('战队名录无效')
    clean_teams = []
    seen_team = {value['teamName'].strip()}
    for team in teams:
        if not isinstance(team, dict):
            raise ValueError('战队条目无效')
        name = team.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 50:
            raise ValueError('战队名称需为 1–50 字')
        name = name.strip()
        if name in seen_team:
            continue
        seen_team.add(name)
        clean_teams.append({
            'id': str(team.get('id') or f'team-{len(clean_teams) + 1}')[:80],
            'name': name,
            'short': str(team.get('short') or '')[:20],
            'coach': str(team.get('coach') or '')[:30],
            'note': str(team.get('note') or '')[:200],
        })
    value['teams'] = clean_teams
    for field in ('aliases', 'enemyAliases'):
        mapping = value.get(field, {})
        if not isinstance(mapping, dict) or len(mapping) > 2000:
            raise ValueError('昵称别名映射无效')
        for label, player_id in mapping.items():
            if (not isinstance(label, str) or not label.strip() or len(label) > 80
                    or player_id not in ids):
                raise ValueError('昵称别名映射包含无效选手或昵称')
        value[field] = mapping
    return value


def check_evidence(c, image_ids, reviews=None):
    from datetime import date
    reviews = reviews or {}
    if not isinstance(reviews, dict) or any(image_id not in image_ids for image_id in reviews):
        raise ValueError('页面校正必须关联本局截图')
    evidence = []
    if not isinstance(image_ids, list) or len(image_ids) > 20 or any(not isinstance(i, str) for i in image_ids) or len(set(image_ids)) != len(image_ids):
        raise ValueError('截图列表无效')
    for image_id in image_ids:
        row = c.execute('SELECT ocr FROM images WHERE id=?', (image_id,)).fetchone()
        if not row:
            raise ValueError('关联截图不存在')
        if row['ocr']:
            recognized = json.loads(row['ocr'])
            corrected = reviews.get(image_id, {})
            if not isinstance(corrected, dict) or not isinstance(corrected.get('scores', {}), dict):
                raise ValueError('页面校正格式错误')
            scores = dict(recognized.get('scores', {}))
            for side, value in corrected.get('scores', {}).items():
                if side not in ('left', 'right') or (value != '' and (not re.fullmatch(r'\d{1,3}', str(value)) or int(value) > 500)):
                    raise ValueError('页面校正比分应为空或 0 至 500 的整数')
                if value == '':
                    scores.pop(side, None)
                else:
                    scores[side] = str(value)
            metadata = dict(recognized.get('meta', {}))
            if 'date' in corrected:
                if corrected['date']:
                    date.fromisoformat(corrected['date'])
                    metadata['date'] = corrected['date']
                else:
                    metadata.pop('date', None)
            evidence.append({**recognized, 'scores': scores, 'meta': metadata})
    for side in ('left', 'right'):
        scores = {int(e['scores'][side]) for e in evidence if side in e.get('scores', {})}
        if len(scores) > 1:
            raise ValueError('关联截图比分冲突：请把不同比赛的截图放到各自草稿')
    dates = {e['meta']['date'] for e in evidence if e.get('meta', {}).get('date')}
    if len(dates) > 1:
        raise ValueError('关联截图日期冲突，请核对是否为同一局')


def validate_icon_reviews(c, m):
    reviews = m.get('iconReviews', [])
    if not isinstance(reviews, list) or len(reviews) > 140:
        raise ValueError('图标核对记录格式错误')
    entries = {e['id']: e for e in catalog()['entries']}
    keys = set()
    for review in reviews:
        if not isinstance(review, dict) or review.get('imageId') not in m.get('imageIds', []):
            raise ValueError('图标核对必须关联本局截图')
        entry = entries.get(review.get('catalogId'))
        if not entry or entry['name'] != review.get('name') or entry['kind'] != review.get('kind'):
            raise ValueError('图标名称与本机目录不匹配')
        row = c.execute('SELECT ocr FROM images WHERE id=?', (review['imageId'],)).fetchone()
        result = json.loads(row['ocr']) if row and row['ocr'] else {}
        matching = [r for r in result.get('visuals', []) if all(r.get(k) == review.get(k) for k in ('side', 'slot', 'kind', 'index'))]
        if len(matching) != 1:
            raise ValueError('图标核对缺少原始识别区域，请重新识别截图')
        key = (review['imageId'], review['side'], review['slot'], review['kind'], review['index'])
        if key in keys:
            raise ValueError('同一图标的核对记录重复')
        keys.add(key)
        review['box'] = matching[0]['box']
        player = next((p for p in m['players'] if p['side'] == review['side'] and p['slot'] == review['slot']), None)
        if review['kind'] == 'hero' and (not player or player.get('hero') != review['name']):
            raise ValueError('英雄已修改，请重新核对对应图标')
        if review['kind'] == 'equipment':
            equipment = player.get('equipmentSlots', []) if player else []
            if len(equipment) != 6 or not isinstance(equipment[review['index']], dict) or equipment[review['index']].get('name') != review['name']:
                raise ValueError('装备已修改，请重新核对对应图标')
    return reviews


def learned_index(c, excluded_image):
    entries = {e['id']: e for e in catalog()['entries']}
    result, prepared, seen = {'hero': [], 'equipment': []}, {}, set()
    for m in records(c):
        if m['status'] != 'confirmed':
            continue
        for review in m.get('iconReviews', []):
            if review.get('kind') != 'equipment':
                continue
            entry = entries.get(review.get('catalogId'))
            image_id = review.get('imageId')
            if not entry or image_id == excluded_image or image_id not in m.get('imageIds', []):
                continue
            player = next((p for p in m['players'] if p['side'] == review.get('side') and p['slot'] == review.get('slot')), None)
            if review.get('kind') == 'hero' and (not player or player.get('hero') != entry['name']):
                continue
            key = (image_id, review['kind'], review['side'], review['slot'], review['index'])
            if key in seen:
                continue
            seen.add(key)
            if image_id not in prepared:
                row = c.execute('SELECT data FROM images WHERE id=?', (image_id,)).fetchone()
                if not row:
                    continue
                prepared[image_id] = prepare_image(bytes(row['data']))[0]
            try:
                vectors = descriptor(crop_box(prepared[image_id], review['box']))
            except (ValueError, KeyError):
                continue
            result[entry['kind']].append(({**entry, 'reviewed': True}, *vectors))
    return result


@app.get('/api/state')
def state():
    with db() as c:
        s = settings(c)
        matches = records(c)
        images = [dict(r) for r in c.execute(
            'SELECT id,name,mime,ocr IS NOT NULL AS recognized, '
            'EXISTS(SELECT 1 FROM postgame_images p WHERE p.id=images.id) AS postgame FROM images')]
    return {'settings': s, 'matches': matches, 'images': images, 'summary': summarize(matches, s['roster'])}


@app.put('/api/settings')
def save_settings(value: dict):
    try:
        with db() as c:
            old = settings(c)
            if isinstance(value, dict):
                value.setdefault('aliases', old.get('aliases', {}))
                value.setdefault('enemyAliases', old.get('enemyAliases', {}))
            value = validate_settings(value)
            previous_team = old['teamName']
            old_teams = {p['id']: p.get('team', previous_team) for p in old['roster']}
            current_team = value['teamName']
            value['customTeams'] = list(dict.fromkeys([*old.get('customTeams', []), previous_team, current_team]))
            for player in value['roster']:
                player.setdefault('team', old_teams.get(player['id'], current_team))
                team = player['team']
                if not isinstance(team, str) or not team.strip() or len(team) > 50 or team == '__custom__':
                    raise ValueError('队员所属战队无效')
                if team not in value['customTeams']:
                    value['customTeams'].append(team)

            if value.get('aliases') != old.get('aliases', {}):
                from analysis_data import AnalysisRepository
                identity_matches = AnalysisRepository(DB_PATH, MATCHES_DIR, IMPORTS_DIR).get()['matches']
                from identity_rules import validate_alias_conflicts
                validate_alias_conflicts(identity_matches, value['roster'], value['aliases'], old.get('aliases', {}))
            if not {p['id'] for p in old['roster']}.issubset({p['id'] for p in value['roster']}):
                raise ValueError('已有队员请保留，避免历史记录失去身份关联')
            c.execute('UPDATE settings SET body=? WHERE id=1', (json.dumps(value, ensure_ascii=False),))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True}


@app.get('/api/focus')
def focus_list():
    with db() as c:
        items = [{'id': r['id'], **json.loads(r['body'])} for r in
                 c.execute('SELECT id, body FROM focus_items ORDER BY created_at')]
    return {'items': items}


@app.post('/api/focus')
def focus_create(value: dict):
    try:
        with db() as c:
            roster_ids = {p['id'] for p in settings(c)['roster']}
            body = focus_module.validate_item(value, roster_ids)
        item_id = uuid.uuid4().hex
        now = time.time()
        with db() as c:
            c.execute('INSERT INTO focus_items(id,body,created_at,updated_at) VALUES(?,?,?,?)',
                      (item_id, json.dumps(body, ensure_ascii=False), now, now))
        return {'ok': True, 'id': item_id, **body}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch('/api/focus/{item_id}')
def focus_update(item_id: str, value: dict):
    try:
        with db() as c:
            row = c.execute('SELECT body FROM focus_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise HTTPException(404, '训练重点不存在')
            body = json.loads(row['body'])
            roster_ids = {p['id'] for p in settings(c)['roster']}
            for key in ('title', 'target', 'status', 'note', 'direction'):
                if key in value:
                    body[key] = value[key]
            body = focus_module.validate_item({**body, 'scopeType': body.get('scopeType'),
                                               'scopeId': body.get('scopeId'), 'metric': body.get('metric')},
                                              roster_ids)
            c.execute('UPDATE focus_items SET body=?, updated_at=? WHERE id=?',
                      (json.dumps(body, ensure_ascii=False), time.time(), item_id))
        return {'ok': True, 'id': item_id, **body}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete('/api/focus/{item_id}')
def focus_delete(item_id: str):
    with db() as c:
        cursor = c.execute('DELETE FROM focus_items WHERE id=?', (item_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, '训练重点不存在')
    return {'ok': True}


@app.get('/api/focus/evaluate')
def focus_evaluate():
    with db() as c:
        items = [{'id': r['id'], **json.loads(r['body'])} for r in
                 c.execute('SELECT id, body FROM focus_items ORDER BY created_at')]
        matches = [json.loads(r['body']) for r in c.execute('SELECT body FROM matches')]
        matches = [match for match in matches if match.get('status') == 'confirmed']
    return {'items': focus_module.evaluate(matches, items)}


@app.get('/api/summary')
def summary(request: Request):
    q = request.query_params
    from domain import POSITIONS
    if q.get('position') and q['position'] not in POSITIONS:
        raise HTTPException(400, '请选择有效的实际分路')
    def selected_player(p):
        return ((not q.get('player') or p.get('playerId') == q['player'])
                and (not q.get('position') or p.get('position') == q['position'])
                and (not q.get('hero') or p.get('hero','').strip() == q['hero'].strip()))
    with db() as c:
        matches = records(c)
        roster = settings(c)['roster']
    filtered = [m for m in matches
                if (not q.get('from') or m.get('date', '') >= q['from'])
                and (not q.get('to') or m.get('date', '') <= q['to'])
                and q.get('opponent', '').strip().lower() in m.get('opponent', '').lower()
                and q.get('version', '').strip().lower() in m.get('version', '').lower()
                and (not any(q.get(k) for k in ('player','position','hero'))
                     or any(p['side'] == m.get('side') and selected_player(p) for p in m['players']))]
    return summarize(filtered, roster, selected_player)


@app.get('/api/matches/{match_id}/review')
def match_review(match_id: str):
    from analytics import review_match
    with db() as c:
        row = c.execute('SELECT body FROM matches WHERE id=?', (match_id,)).fetchone()
        s = settings(c)
    if not row:
        raise HTTPException(404, '比赛不存在')
    return review_match(json.loads(row['body']), s['roster'], s['teamName'])


@app.post('/api/matches')
def save_match(value: dict):
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            m = validate_match(value, settings(c)['roster'])
            match_id = m.get('id') or str(uuid.uuid4())
            old = c.execute('SELECT revision FROM matches WHERE id=?', (match_id,)).fetchone()
            if old and m.get('revision') != old[0]:
                raise HTTPException(409, '比赛已被另一个窗口修改，请刷新后重新打开')
            image_ids = m.get('imageIds', [])
            if not isinstance(image_ids, list) or len(image_ids) > 20 or len(set(image_ids)) != len(image_ids):
                raise ValueError('截图列表无效')
            evidence = []
            for image_id in image_ids:
                image = c.execute('SELECT id,ocr FROM images WHERE id=?', (image_id,)).fetchone()
                if not image:
                    raise ValueError('关联截图不存在')
                if image['ocr']:
                    evidence.append(json.loads(image['ocr']))
            validate_icon_reviews(c, m)
            # Any OCR page conflict blocks confirmation, even if the user never applies it.
            if m['status'] == 'confirmed':
                check_evidence(c, image_ids, m.get('evidenceReviews'))
                for other in records(c):
                    if other['id'] != match_id and other['status'] == 'confirmed' and set(other.get('imageIds', [])) & set(image_ids):
                        raise HTTPException(409, '相同截图已经关联另一场正式比赛，请检查是否重复入库')
            m['id'], m['revision'], m['updatedAt'] = match_id, old[0] + 1 if old else 1, time.time()
            body = json.dumps(m, ensure_ascii=False, allow_nan=False)
            c.execute('INSERT INTO matches VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, body=excluded.body', (match_id, m['revision'], body))
            c.execute('INSERT INTO revisions(match_id,saved_at,body) VALUES(?,?,?)', (match_id, time.time(), body))
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, str(e))
    return m


@app.post('/api/images')
async def upload_image(request: Request):
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > MAX_IMAGE:
            raise HTTPException(413, '单张截图请小于 12 MB')
        chunks.append(chunk)
    data = b''.join(chunks)
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 24000000 or im.width < 100 or im.height < 100:
                raise ValueError('图片尺寸不适合识别（需至少 100×100，最多 2400 万像素）')
            mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(im.format)
            if not mime:
                raise ValueError('支持 PNG、JPEG 或 WebP 图片')
            im.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise HTTPException(400, f'无法读取截图：{e}')
    image_id = hashlib.sha256(data).hexdigest()
    name = request.query_params.get('name', '截图')[:200]
    with db() as c:
        c.execute('INSERT OR IGNORE INTO images(id,name,mime,data) VALUES (?,?,?,?)', (image_id, name, mime, data))
    return {'id': image_id, 'name': name, 'mime': mime}


@app.get('/api/images/{image_id}')
def image(image_id: str):
    with db() as c:
        row = c.execute('SELECT mime,data FROM images WHERE id=?', (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, '截图不存在')
    return Response(bytes(row['data']), media_type=row['mime'])


@app.get('/api/catalog')
def get_catalog():
    value = catalog()
    return {'updatedAt': value.get('updatedAt'), 'notice': value.get('notice'),
            'entries': [{k: e.get(k) for k in ('id', 'kind', 'name', 'icon')} for e in value['entries']]}


@app.get('/api/images/{image_id}/crop')
def icon_crop(image_id: str, x1: float, y1: float, x2: float, y2: float):
    with db() as c:
        row = c.execute('SELECT data FROM images WHERE id=?', (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, '截图不存在')
    try:
        cropped = crop_box(prepare_image(bytes(row['data']))[0], [x1, y1, x2, y2])
        stream = io.BytesIO()
        cropped.resize((cropped.width*3, cropped.height*3)).save(stream, format='PNG')
    except ValueError as error:
        raise HTTPException(400, str(error))
    return Response(stream.getvalue(), media_type='image/png')


@app.get('/api/images/{image_id}/recognition')
def cached_recognition(image_id: str):
    with db() as c:
        row = c.execute('SELECT ocr FROM images WHERE id=?', (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, '截图不存在')
    if not row['ocr']:
        return None
    result = json.loads(row['ocr'])
    if result.get('version') and result['version'] != OCR_VERSION:
        result['visuals'] = []
        result.setdefault('warnings', []).append('旧版图标候选已停用，请点击重新识别读取英雄名称。')
    return result


@app.post('/api/images/{image_id}/ocr')
def ocr_image(image_id: str, refresh: bool = False):
    with db() as c:
        row = c.execute('SELECT data,ocr FROM images WHERE id=?', (image_id,)).fetchone()
        learned = learned_index(c, image_id) if row else {}
    if not row:
        raise HTTPException(404, '截图不存在')
    if row['ocr'] and not refresh:
        cached = json.loads(row['ocr'])
        if cached.get('version') == OCR_VERSION:
            return cached
    try:
        result = recognize(bytes(row['data']), learned)
    except ImportError:
        raise HTTPException(503, '本地 OCR 组件未安装，请运行安装依赖.bat；仍可手动录入')
    except Exception as e:
        raise HTTPException(422, f'识别失败，可继续手动录入（{type(e).__name__}）')
    with db() as c:
        c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps(result, ensure_ascii=False), image_id))
    return result


@app.patch('/api/postgame/images/hero')
def postgame_edit_hero(value: dict):
    image_ids = value.get('imageIds')
    side, slot = value.get('side'), value.get('slot')
    hero = str(value.get('hero') or '').strip()
    if not isinstance(image_ids, list) or not image_ids:
        raise HTTPException(400, '缺少截图组')
    if side not in ('left', 'right') or not isinstance(slot, int) or slot not in range(5):
        raise HTTPException(400, '选手位置无效')
    names = {entry['name'] for entry in catalog()['entries'] if entry['kind'] == 'hero'}
    if hero and hero not in names:
        raise HTTPException(400, '英雄不在本机目录中')
    with db() as c:
        rows = c.execute('SELECT id,result FROM postgame_images WHERE id IN (%s)' %
                         ','.join('?' for _ in image_ids), tuple(image_ids)).fetchall()
        if len(rows) != len(set(image_ids)):
            raise HTTPException(400, '部分截图缺少识别结果')
        for row in rows:
            result = json.loads(row['result'])
            player = next((item for item in result.get('players', [])
                           if item.get('side') == side and item.get('slot') == slot), None)
            if not player:
                raise HTTPException(400, '该截图组缺少指定选手')
            if hero:
                player['hero'] = {'value': hero, 'raw': hero, 'confidence': 1.0, 'box': None}
                player['heroStatus'] = 'manual'
                player['heroSource'] = 'manual'
            else:
                player['hero'] = None
                player['heroStatus'] = 'unreadable'
                player['heroSource'] = 'manual'
            c.execute('UPDATE postgame_images SET result=?, updated_at=? WHERE id=?',
                      (json.dumps(result, ensure_ascii=False), time.time(), row['id']))
    return {'ok': True, 'side': side, 'slot': slot, 'hero': hero or None, 'updated': len(rows)}


def _manual_hero_fields(result):
    fields = {}
    for player in (result or {}).get('players') or []:
        if player.get('heroSource') == 'manual' and player.get('hero'):
            fields[(player.get('side'), player.get('slot'))] = dict(player['hero'])
    return fields


def _preserve_manual_heroes(result, previous):
    manual = _manual_hero_fields(previous)
    if not manual:
        return result
    for player in result.get('players') or []:
        hero = manual.get((player.get('side'), player.get('slot')))
        if not hero:
            continue
        if player.get('heroSource') != 'manual':
            player['hero'] = hero
            player['heroStatus'] = 'manual'
            player['heroSource'] = 'manual'
    return result


@app.post('/api/postgame/images/{image_id}/ocr')
def postgame_ocr_image(image_id: str, refresh: bool = False):
    with db() as c:
        image = c.execute('SELECT name,data FROM images WHERE id=?', (image_id,)).fetchone()
        cached = c.execute('SELECT result FROM postgame_images WHERE id=?', (image_id,)).fetchone()
    if not image:
        raise HTTPException(404, '截图不存在')
    previous = None
    if cached:
        try:
            previous = json.loads(cached['result'])
        except (TypeError, ValueError):
            previous = None
    if previous and not refresh:
        if previous.get('version') == POSTGAME_OCR_VERSION:
            previous.setdefault('imageId', image_id)
            previous.setdefault('imageName', image['name'])
            return previous
    try:
        result = recognize_postgame(bytes(image['data']), name=image['name'])
    except ImportError:
        raise HTTPException(503, '本地 OCR 组件未安装，请运行安装依赖.bat')
    except Exception as e:
        raise HTTPException(422, f'分页截图识别失败（{type(e).__name__}）')
    result = _preserve_manual_heroes(result, previous)
    result['imageId'] = image_id
    result['imageName'] = image['name']
    with db() as c:
        c.execute('INSERT INTO postgame_images(id,result,updated_at) VALUES(?,?,?) '
                  'ON CONFLICT(id) DO UPDATE SET result=excluded.result, updated_at=excluded.updated_at',
                  (image_id, json.dumps(result, ensure_ascii=False), time.time()))
    return result


def _postgame_collection(c):
    rows = c.execute('SELECT p.id,p.result,p.updated_at,i.name,i.mime FROM postgame_images p '
                     'JOIN images i ON i.id=p.id ORDER BY p.updated_at DESC').fetchall()
    results = []
    images = []
    for row in rows:
        try:
            result = json.loads(row['result'])
        except (TypeError, ValueError):
            continue
        result['imageId'] = row['id']
        result['imageName'] = row['name']
        result['demo'] = bool(result.get('demo'))
        results.append(result)
        images.append({
            'id': row['id'], 'name': row['name'], 'mime': row['mime'],
            'pageType': result.get('pageType'), 'tab': result.get('tab'),
            'layout': result.get('layout') or POSTGAME_OCR_VERSION,
            'match': result.get('match') or {}, 'coverage': result.get('coverage') or {},
            'warnings': result.get('warnings') or [], 'updatedAt': row['updated_at'],
            'quality': result.get('quality'), 'engine': result.get('engine'),
            'mimo': result.get('mimo'), 'refineVersion': result.get('refineVersion'),
            'demo': result['demo'],
        })
    groups = merge_postgame_pages(results) if results else []
    by_image = {result['imageId']: result for result in results}
    for group in groups:
        group['imageIds'] = [page.get('imageId') for page in group.get('pages', []) if page.get('imageId')]
        group['demo'] = bool(group['imageIds']) and all(by_image.get(image_id, {}).get('demo') for image_id in group['imageIds'])
    groups.sort(key=lambda group: (
        0 if (group.get('match') or {}).get('date') else 1,
        0 if ((group.get('match') or {}).get('score') or {}).get('left') is not None else 1,
        -len(group.get('pages') or []),
        ((group.get('match') or {}).get('date') or ''),
    ))
    for group in groups:
        group['analysis'] = analyze_group(group)
    return {'schema': 'kpl-postgame-collection-v1', 'images': images, 'groups': groups}


@app.get('/api/postgame/images')
def postgame_images():
    with db() as c:
        return _postgame_collection(c)


POSTGAME_DEMO_FILES = (
    '01-score.png', '02-kda.png', '03-farming.png', '04-survival.png',
    '05-data.png', '06-output.png', '07-team.png',
)


@app.post('/api/postgame/demo')
def load_postgame_demo():
    folder = DATA_DIR / 'screenshots' / 'samples'
    paths = [folder / name for name in POSTGAME_DEMO_FILES]
    if not all(path.is_file() for path in paths):
        raise HTTPException(404, '缺少示例截图目录 data/screenshots/samples')
    for path in paths:
        data = path.read_bytes()
        image_id = hashlib.sha256(data).hexdigest()
        with db() as c:
            c.execute('INSERT OR IGNORE INTO images(id,name,mime,data) VALUES(?,?,?,?)',
                      (image_id, path.name, 'image/png', data))
            cached = c.execute('SELECT result FROM postgame_images WHERE id=?', (image_id,)).fetchone()
        if cached:
            cached_result = json.loads(cached['result'])
            if cached_result.get('version') == POSTGAME_OCR_VERSION:
                continue
        try:
            result = recognize_postgame(data, name=path.name)
        except ImportError:
            raise HTTPException(503, '本地 OCR 组件未安装，请运行安装依赖.bat')
        except Exception as e:
            raise HTTPException(422, f'示例截图识别失败（{path.name}: {type(e).__name__}）')
        result['imageId'] = image_id
        result['imageName'] = path.name
        result['demo'] = True
        with db() as c:
            c.execute('INSERT INTO postgame_images(id,result,updated_at) VALUES(?,?,?) '
                      'ON CONFLICT(id) DO UPDATE SET result=excluded.result, updated_at=excluded.updated_at',
                      (image_id, json.dumps(result, ensure_ascii=False), time.time()))
    with db() as c:
        return _postgame_collection(c)


@app.delete('/api/postgame/demo')
def clear_postgame_demo():
    removed = 0
    with db() as c:
        rows = c.execute('SELECT id,result FROM postgame_images').fetchall()
        for row in rows:
            try:
                result = json.loads(row['result'])
            except (TypeError, ValueError):
                continue
            if result.get('demo'):
                c.execute('DELETE FROM postgame_images WHERE id=?', (row['id'],))
                removed += 1
    return {'removed': removed}


@app.delete('/api/postgame/images/{image_id}')
def delete_postgame_image(image_id: str):
    with db() as c:
        row = c.execute('SELECT 1 FROM postgame_images WHERE id=?', (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, '截图采集结果不存在')
        c.execute('DELETE FROM postgame_images WHERE id=?', (image_id,))
    return {'ok': True}


# ---------------------------------------------------------------------------
# Local OCR engines and background refinement jobs

def _refine_postgame_group(image_ids, force=False):
    def runner(job):
        total = max(1, len(image_ids))
        refined, skipped = 0, []
        for index, image_id in enumerate(image_ids):
            job.check_cancelled()
            with db() as c:
                image = c.execute('SELECT name,data FROM images WHERE id=?', (image_id,)).fetchone()
                cached = c.execute('SELECT result FROM postgame_images WHERE id=?', (image_id,)).fetchone()
            if not image or not cached:
                skipped.append(image_id)
                continue
            try:
                previous = json.loads(cached['result'])
            except (TypeError, ValueError):
                skipped.append(image_id)
                continue
            base = 5 + int(index / total * 85)
            job.stage(f'Mimo 精读 {index + 1}/{total}', base, image['name'])

            def on_stage(stage, base=base):
                job.stage(stage, min(92, base + 2))

            refined_result = postgame_mimo.refine(
                bytes(image['data']), previous, name=image['name'],
                on_stage=on_stage, force=force)
            # Re-read the row: the user may have fixed a hero while Mimo was running.
            with db() as c:
                current = c.execute('SELECT result FROM postgame_images WHERE id=?',
                                    (image_id,)).fetchone()
            if current:
                try:
                    refined_result = _preserve_manual_heroes(
                        refined_result, json.loads(current['result']))
                except (TypeError, ValueError):
                    pass
            refined_result['imageId'] = image_id
            refined_result['imageName'] = image['name']
            with db() as c:
                c.execute('UPDATE postgame_images SET result=?, updated_at=? WHERE id=?',
                          (json.dumps(refined_result, ensure_ascii=False), time.time(), image_id))
            refined += 1
        return {'refined': refined, 'skipped': skipped}
    return runner


@app.get('/api/ocr/status')
def ocr_status():
    rapid = importlib.util.find_spec('rapidocr_onnxruntime') is not None
    try:
        db_free = shutil.disk_usage(DB_PATH.parent).free
    except OSError:
        db_free = 0
    return {
        'mimo': mimo_ocr.status(),
        'rapid': {'engine': 'rapidocr-onnxruntime', 'available': rapid},
        'ffmpeg': media_tools.available(),
        'ffprobe': media_tools.probe_available(),
        'ffmpegSource': media_tools.source(),
        'storage': {'dbPath': str(DB_PATH), 'dbFreeBytes': db_free,
                    'recordingsFreeBytes': recording_store.free_bytes()},
        'jobs': ocr_jobs.list_jobs(limit=12),
        'recordings': recording_store.library_stats(),
    }


# ---------------- OCR 组件的一键安装 ----------------
#
# 主 OCR（rapidocr）与可选的 Mimo 精读都要额外装依赖，Mimo 还要约 2 GB 模型权重。
# 做法统一成「检测 → 点安装 → 后台跑 → 完成提示」：安装是服务端线程，
# 切页面不会中断；页面只轮询 /api/ocr/install 的进度。

_OCR_INSTALL_LOCK = threading.Lock()
_OCR_INSTALL_JOB = {
    'running': False, 'target': '', 'phase': '', 'message': '', 'percent': 0,
    'error': '', 'startedAt': None, 'finishedAt': None,
    'bytes': 0, 'totalBytes': 0, 'log': [],
}

_OCR_INSTALL_TARGETS = {
    'rapid': {'file': 'requirements-ocr.txt', 'label': '主 OCR'},
    'mimo': {'file': 'requirements-mimo.txt', 'label': 'Mimo 精读'},
    # ffmpeg 不走 pip：直接下一份静态包解压到 tools/ffmpeg，不动系统 PATH。
    'ffmpeg': {'file': None, 'label': 'ffmpeg'},
}

# 静态包：BtbN 的 GitHub 构建优先（实测国内 3–4 MB/s），gyan.dev 官方兜底（实测常只有几十 KB/s）。
_FFMPEG_URLS = (
    'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/'
    'ffmpeg-master-latest-win64-gpl.zip',
    'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
)


def _ocr_install_update(**fields) -> None:
    with _OCR_INSTALL_LOCK:
        _OCR_INSTALL_JOB.update(fields)
        _OCR_INSTALL_JOB['log'] = (_OCR_INSTALL_JOB.get('log') or [])[-40:]


def _pip_install(requirement_name: str) -> tuple[bool, str]:
    requirement = ROOT / requirement_name
    if not requirement.is_file():
        return False, f'安装包里缺少 {requirement_name}'
    base = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
            '--progress-bar', 'off', '-r', str(requirement)]
    last = ''
    seen = 0
    for index, extra in enumerate((['-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'], [])):
        if index:
            _ocr_install_update(message='国内镜像失败，改用官方源重试…', phase='deps')
        proc = subprocess.Popen(base + extra, cwd=str(ROOT), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                errors='replace', bufsize=1)
        for raw in proc.stdout:
            line = (raw or '').strip()
            if not line:
                continue
            last = line
            if line.startswith(('Collecting ', 'Downloading ', 'Installing ')):
                seen += 1
                _ocr_install_update(phase='deps', percent=min(58, 8 + seen * 4),
                                    message=line[:120])
            else:
                _ocr_install_update(phase='deps', message=line[:120])
        if proc.wait() == 0:
            return True, last
    return False, last


def _download_mimo_model() -> None:
    """把模型拉到 models/Xiaomi-OCR-0；官方源失败时切镜像再试一次。"""
    target = ROOT / 'models' / 'Xiaomi-OCR-0'
    target.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import HfApi, snapshot_download
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f'依赖里缺少 huggingface_hub：{error}')

    total = 0
    try:
        info = HfApi().model_info(mimo_ocr.MODEL_REPO, files_metadata=True)
        total = sum(int(getattr(item, 'size', 0) or 0) for item in (info.siblings or []))
    except Exception:
        total = 0
    _ocr_install_update(phase='model', percent=60, bytes=0, totalBytes=total,
                        message='正在下载模型（首次较大，可以切页面，装完会提示）')

    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(2):
            size = 0
            for path in target.rglob('*'):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except OSError:
                    continue
            percent = 60 + int(35 * size / total) if total else 60
            text = f'正在下载模型 {size / 1024 ** 3:.1f} GB'
            if total:
                text += f' / {total / 1024 ** 3:.1f} GB'
            _ocr_install_update(bytes=size, percent=min(95, percent), message=text)

    threading.Thread(target=watch, daemon=True, name='mimo-model-watch').start()
    previous_endpoint = os.environ.get('HF_ENDPOINT')
    last_error = ''
    try:
        for endpoint in (None, 'https://hf-mirror.com'):
            if endpoint:
                os.environ['HF_ENDPOINT'] = endpoint
                _ocr_install_update(message=f'官方源失败，改用镜像 {endpoint} 重试…')
            try:
                snapshot_download(repo_id=mimo_ocr.MODEL_REPO, local_dir=str(target))
                last_error = ''
                break
            except Exception as error:  # noqa: BLE001 - 换源之前先记下原因
                last_error = f'{type(error).__name__}: {error}'
        if last_error:
            raise RuntimeError(last_error)
    finally:
        stop.set()
        if previous_endpoint is None:
            os.environ.pop('HF_ENDPOINT', None)
        else:
            os.environ['HF_ENDPOINT'] = previous_endpoint


def _install_ffmpeg() -> None:
    """下载 ffmpeg 静态包并解压到 tools/ffmpeg/bin（不需要管理员权限）。"""
    import tempfile
    import urllib.request
    import zipfile

    destination = media_tools.LOCAL_ROOT
    destination.mkdir(parents=True, exist_ok=True)
    error = ''
    for url in _FFMPEG_URLS:
        _ocr_install_update(phase='deps', percent=6, message=f'正在下载 ffmpeg…（{url.split("/")[2]}）')
        try:
            with tempfile.TemporaryDirectory(prefix='kpl-ffmpeg-') as tmp:
                archive = Path(tmp) / 'ffmpeg.zip'
                with urllib.request.urlopen(url, timeout=60) as response:
                    total = int(response.headers.get('Content-Length') or 0)
                    done = 0
                    with open(archive, 'wb') as handle:
                        while True:
                            chunk = response.read(512 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                            done += len(chunk)
                            percent = 6 + int(70 * done / total) if total else 40
                            _ocr_install_update(
                                phase='deps', percent=min(78, percent), bytes=done,
                                totalBytes=total,
                                message=f'正在下载 ffmpeg {done / 1024 ** 2:.0f}'
                                        + (f' / {total / 1024 ** 2:.0f}' if total else '') + ' MB')
                _ocr_install_update(phase='deps', percent=80, message='正在解压 ffmpeg…')
                with zipfile.ZipFile(archive) as bundle:
                    member = next((n for n in bundle.namelist()
                                   if n.replace('\\', '/').endswith('/bin/ffmpeg.exe')), None)
                    if member is None:
                        raise RuntimeError('压缩包里没有找到 ffmpeg.exe')
                    prefix = member.replace('\\', '/')[:-len('ffmpeg.exe')]
                    wanted = [n for n in bundle.namelist()
                              if n.replace('\\', '/').startswith(prefix)
                              and not n.endswith('/')]
                    bin_dir = destination / 'bin'
                    bin_dir.mkdir(parents=True, exist_ok=True)
                    for name in wanted:
                        flat = name.replace('\\', '/')[len(prefix):]
                        # ffplay 用不上，跳过能省 160 MB。
                        if '/' in flat or flat.lower() not in ('ffmpeg.exe', 'ffprobe.exe'):
                            continue
                        with bundle.open(name) as src, open(bin_dir / flat, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
            if media_tools.local_exe('ffmpeg') is None:
                raise RuntimeError('解压后仍找不到 ffmpeg.exe')
            _ocr_install_update(phase='deps', percent=92, message='正在校验 ffprobe…')
            if media_tools.local_exe('ffprobe') is None:
                raise RuntimeError('解压后缺少 ffprobe.exe')
            error = ''
            break
        except Exception as exc:  # noqa: BLE001 - 换源继续，最后统一报错
            error = f'{type(exc).__name__}: {exc}'
            _ocr_install_update(message=f'这个源不行，换下一个…（{error[:80]}）')
    if error:
        raise RuntimeError(f'ffmpeg 下载失败：{error}')


_OCR_AUTO_INSTALL_RETRY_SECONDS = 24 * 3600


def maybe_auto_install_ocr(*, available=None, start=None, marker=None) -> dict:
    """首次启动静默补装主 OCR；失败后每天最多重试一次。

    背景：Gitee 渠道完整包受附件 100MB 限制不含 OCR 运行时，用户装完打开
    工作台不应再手动找安装入口。这里在服务启动后自动安装一次，进度显示在
    「识别引擎」面板；KPL_OCR_AUTO_INSTALL=0 可关闭。参数可注入便于测试。
    """
    if os.environ.get('KPL_OCR_AUTO_INSTALL', '').strip().lower() in ('0', 'false', 'off', 'no'):
        return {'started': False, 'reason': 'disabled'}
    if available is None:
        available = importlib.util.find_spec('rapidocr_onnxruntime') is not None
    if available:
        return {'started': False, 'reason': 'already-installed'}
    marker = Path(marker) if marker is not None else data_root() / 'ocr_auto_install.json'
    now = time.time()
    try:
        last = float((json.loads(marker.read_text(encoding='utf-8')) or {}).get('lastAttempt') or 0)
    except (OSError, ValueError):
        last = 0.0
    if now - last < _OCR_AUTO_INSTALL_RETRY_SECONDS:
        return {'started': False, 'reason': 'throttled'}
    with _OCR_INSTALL_LOCK:
        if _OCR_INSTALL_JOB.get('running'):
            return {'started': False, 'reason': 'busy'}
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'lastAttempt': now, 'reason': 'auto'}), encoding='utf-8')
    except OSError:
        pass

    def _default_start():
        threading.Thread(target=_ocr_install_worker, args=('rapid',), daemon=True).start()
    (start or _default_start)()
    return {'started': True, 'reason': 'started'}


@app.on_event('startup')
def _startup_auto_install_ocr():
    try:
        maybe_auto_install_ocr()
    except Exception:  # noqa: BLE001 - 自动安装失败不影响服务启动
        pass


def _ocr_install_worker(target: str) -> None:
    spec = _OCR_INSTALL_TARGETS[target]
    try:
        if target == 'ffmpeg':
            _ocr_install_update(phase='deps', percent=4, message='正在安装 ffmpeg（约 200 MB，视网速 1–5 分钟）…')
            _install_ffmpeg()
            _ocr_install_update(running=False, phase='done', percent=100,
                                message='ffmpeg 已就绪，不用重启', finishedAt=time.time())
            return
        _ocr_install_update(phase='deps', percent=4,
                            message=f'正在安装{spec["label"]}组件（首次较慢）…')
        ok, last = _pip_install(spec['file'])
        if not ok:
            raise RuntimeError(f'{spec["label"]}安装失败：{last or "未知错误"}')
        if target == 'mimo':
            _ocr_install_update(phase='deps', percent=60, message='依赖装好了，检查模型…')
            if mimo_ocr.model_path() is None:
                _download_mimo_model()
        _ocr_install_update(running=False, phase='done', percent=100,
                            message=f'{spec["label"]}已就绪，不用重启', finishedAt=time.time())
    except BaseException as error:  # noqa: BLE001 - 失败原因要原样回到页面
        _ocr_install_update(running=False, phase='error', percent=0,
                            error=f'{type(error).__name__}: {error}',
                            message=str(error)[:200], finishedAt=time.time())


@app.get('/api/ocr/install')
def ocr_install_status():
    with _OCR_INSTALL_LOCK:
        job = dict(_OCR_INSTALL_JOB)
    rapid = importlib.util.find_spec('rapidocr_onnxruntime') is not None
    return {**job, 'rapid': {'available': rapid}, 'mimo': mimo_ocr.status(),
            'ffmpeg': {'available': media_tools.available(),
                       'source': media_tools.source()}}


@app.post('/api/ocr/install')
def ocr_install_start(target: str = 'mimo'):
    target = str(target or 'mimo').lower()
    if target not in _OCR_INSTALL_TARGETS:
        raise HTTPException(400, '安装目标需为 rapid、mimo 或 ffmpeg')
    requirement = _OCR_INSTALL_TARGETS[target]['file']
    if requirement and not (ROOT / requirement).is_file():
        raise HTTPException(400, f'安装包里缺少 {requirement}，请更新到最新版本')
    if target == 'ffmpeg':
        try:
            free = shutil.disk_usage(ROOT).free
        except OSError:
            free = 0
        if free and free < 900 * 1024 ** 2:
            raise HTTPException(400, f'磁盘剩余 {free / 1024 ** 2:.0f} MB，安装 ffmpeg 至少要 900 MB')
    elif target == 'mimo':
        try:
            free = shutil.disk_usage(ROOT).free
        except OSError:
            free = 0
        if free and free < 4 * 1024 ** 3:
            raise HTTPException(400, f'磁盘剩余 {free / 1024 ** 3:.1f} GB，安装 Mimo 至少要 4 GB')
    else:
        try:
            free = shutil.disk_usage(ROOT).free
        except OSError:
            free = 0
        if free and free < 1024 ** 3:
            raise HTTPException(400, f'磁盘剩余 {free / 1024 ** 3:.1f} GB，安装主 OCR 至少要 1 GB')
    with _OCR_INSTALL_LOCK:
        if _OCR_INSTALL_JOB['running']:
            raise HTTPException(409, '正在进行安装，请稍候')
        _OCR_INSTALL_JOB.update({'running': True, 'target': target, 'phase': 'prepare',
                                 'percent': 2, 'message': '正在准备安装…', 'error': '',
                                 'log': [], 'startedAt': time.time(), 'finishedAt': None,
                                 'bytes': 0, 'totalBytes': 0})
    threading.Thread(target=_ocr_install_worker, args=(target,), daemon=True,
                     name='ocr-install').start()
    return {'ok': True, 'target': target}


@app.post('/api/postgame/images/{image_id}/refine')
def refine_postgame_image(image_id: str, force: bool = False):
    with db() as c:
        image = c.execute('SELECT 1 FROM images WHERE id=?', (image_id,)).fetchone()
        cached = c.execute('SELECT 1 FROM postgame_images WHERE id=?', (image_id,)).fetchone()
    if not image:
        raise HTTPException(404, '截图不存在')
    if not cached:
        raise HTTPException(409, '请先完成快速识别，再进行 Mimo 精读')
    active = ocr_jobs.find_active('postgame-refine', image_id)
    if active:
        return active
    return ocr_jobs.submit('postgame-refine', image_id,
                           _refine_postgame_group([image_id], force),
                           meta={'imageId': image_id})


@app.post('/api/postgame/refine')
def refine_postgame_batch(value: dict):
    image_ids = value.get('imageIds')
    if not isinstance(image_ids, list) or not 1 <= len(image_ids) <= 50 or \
            any(not isinstance(item, str) for item in image_ids) or len(set(image_ids)) != len(image_ids):
        raise HTTPException(400, '截图列表无效')
    with db() as c:
        rows = c.execute('SELECT id FROM postgame_images WHERE id IN (%s)' %
                         ','.join('?' for _ in image_ids), tuple(image_ids)).fetchall()
    if len(rows) != len(image_ids):
        raise HTTPException(409, '部分截图还没有快速识别结果')
    active = ocr_jobs.find_active('postgame-group', 'group')
    if active:
        return active
    return ocr_jobs.submit('postgame-group', 'group',
                           _refine_postgame_group(image_ids, bool(value.get('force'))),
                           meta={'imageIds': image_ids})


@app.get('/api/ocr/jobs')
def list_ocr_jobs(kind: str = '', target: str = '', limit: int = 30):
    return {'jobs': ocr_jobs.list_jobs(kind=kind or None, target_id=target or None,
                                       limit=max(1, min(80, int(limit))))}


@app.get('/api/ocr/jobs/{job_id}')
def get_ocr_job(job_id: str):
    job = ocr_jobs.get(job_id)
    if not job:
        raise HTTPException(404, '任务不存在或已过期')
    return job


@app.post('/api/ocr/jobs/{job_id}/cancel')
def cancel_ocr_job(job_id: str):
    job = ocr_jobs.cancel(job_id)
    if not job:
        raise HTTPException(404, '任务不存在或已过期')
    if job.get('kind') == 'recording' and job.get('status') == 'queued' and job.get('targetId'):
        try:
            recording_store.update_meta(job['targetId'], status='cancelled',
                                        stage='已取消', error=None)
        except recording_store.RecordingError:
            pass
    return job


# ---------------------------------------------------------------------------
# Camp public replay links: official 30s gold, events and 1s positions

@app.post('/api/official/replay')
def import_official_replay(value: dict):
    url = value.get('url')
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(400, '请粘贴王者营地回放链接')
    try:
        result = camp_replay.import_link(url.strip(), force=bool(value.get('force')))
    except camp_replay.CampReplayError as error:
        raise HTTPException(400, str(error))
    return {'ok': True, 'id': result['id'], 'meta': result['meta'],
            'cached': bool(result.get('cached'))}


@app.post('/api/official/replays/batch')
def import_official_replays_batch(value: dict):
    """批量粘贴营地分享链接：逐条解析导入，失败不拖垮整批。

    输入 {"text": "粘贴内容"}，文本里的 URL 按空白切分、自动去重，
    单次最多 20 条；短链（cu.qq.com 等）在后端自动展开。
    """
    text = value.get('text')
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(400, '请粘贴包含营地链接的内容')
    urls = re.findall(r'https?://[^\s<>"\'，。；、）)】\]]+', text)
    seen, ordered = set(), []
    for url in urls:
        url = url.strip().rstrip(',.;。')
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    if not ordered:
        raise HTTPException(400, '粘贴内容里没有找到链接')
    if len(ordered) > 20:
        raise HTTPException(400, f'一次最多处理 20 条，收到 {len(ordered)} 条')
    items = []
    for url in ordered:
        entry = {'url': url}
        share_user_id = None
        try:
            # 分享链接自带分享者的营地 ID（userId=），顺便提取出来供同步清单登记
            share_url = url
            if camp_replay.is_short_link(share_url):
                share_url = camp_replay.expand_short_link(share_url)
            share_user_id = camp_replay.extract_camp_user_id(share_url).get('userId')
        except Exception:
            # 只影响「清单+」快捷按钮，不让整批导入失败
            share_user_id = None
        try:
            result = camp_replay.import_link(share_url, force=bool(value.get('force')))
            meta = result.get('meta') or {}
            match = meta.get('match') or {}
            entry.update({
                'ok': True,
                'id': result.get('id'),
                'gameSeq': meta.get('gameSeq'),
                'battleType': meta.get('battleType'),
                'pvpType': meta.get('pvpType'),
                'winCamp': match.get('winCamp'),
                'durationSec': match.get('durationSec'),
                'teamGold': match.get('teamGold'),
                'goldPoints': match.get('goldPoints'),
                'cached': bool(result.get('cached')),
                'shareUserId': share_user_id,
            })
        except camp_replay.CampReplayError as error:
            entry.update({'ok': False, 'error': str(error)})
        except Exception as error:  # 网络/磁盘等意外，同样不让整批失败
            entry.update({'ok': False, 'error': f'{type(error).__name__}: {error}'})
        items.append(entry)
    imported = sum(1 for item in items if item['ok'])
    return {'schema': 'camp-replay-batch-v1', 'total': len(items),
            'imported': imported, 'failed': len(items) - imported, 'items': items}


@app.get('/api/official/archive')
def official_archive(replay_id: str = '', limit: int = 0):
    """营地载荷的字段档案：训练赛组问「你们到底爬了什么」，答案在这里。

    不带 `replay_id` 返回跨局索引；带 `replay_id` 返回那一条回放的完整字段表
    与中文文案。档案是 `scripts/archive_camp_fields.py` 落盘的只读产物。
    """
    import camp_archive
    store = camp_replay.STORE
    if replay_id:
        path = store / replay_id / 'fields.json'
        payload = camp_replay_read_json(path)
        if payload is None:
            raw = camp_replay_read_json(store / replay_id / 'raw.json')
            if raw is None:
                raise HTTPException(404, '这条回放没有字段档案')
            payload = camp_archive.build_for_replay(replay_id, store=store)
        return payload
    index = camp_replay_read_json(store / '_fields-index.json')
    if index is None:
        index = camp_archive.scan(store, limit=limit or None)
    summary = camp_replay_read_json(DATA_DIR / 'camp_fields_summary.json') or {}
    labels = camp_archive.load_labels(ROOT)
    return {'summary': summary, 'sources': index,
            'frontendLabels': {'count': labels.get('count', 0),
                               'labels': (labels.get('labels') or [])[:200]}}


def camp_replay_read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


@app.get('/api/official/replays')
def list_official_replays():
    return {'schema': 'camp-replay-v1', 'replays': camp_replay.list_replays()}


@app.get('/api/official/coverage')
def official_coverage():
    """官方回放覆盖面：通道里有多少局真的拿到了回放，清单里还能补多少局。

    教练问的是「这些图为什么是空的」，答案几乎总是「这一局没有回放」。
    把「本机清单里还能补」和「清单里也没有」分开报，空态才有下一步。
    """
    with db() as c:
        rows = c.execute('SELECT body FROM channels').fetchall()
    channels, with_replay, saved_without = 0, 0, 0
    pending = []
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        channels += 1
        official = channel.get('official') or {}
        seq = str(official.get('id') or '')
        seq = seq[5:] if seq.startswith('camp-') else ''
        if seq and (camp_replay.STORE / f'camp-{seq}' / 'meta.json').is_file():
            with_replay += 1
            continue
        saved = (channel.get('saved') or {}).get('status') == 'saved'
        if saved:
            saved_without += 1
        if seq:
            pending.append({'gameSeq': seq, 'channelId': channel.get('id'), 'saved': saved})
    index = _camp_official_index()
    fillable = [item for item in pending if item['gameSeq'] in index]
    return {'channels': channels, 'withReplay': with_replay,
            'savedWithoutReplay': saved_without,
            'pending': len(pending), 'fillable': len(fillable),
            'listed': len(index), 'sample': fillable[:20]}


@app.post('/api/official/backfill')
def official_backfill(value: dict):
    """把清单里还能补的官方回放一次性拉下来（默认最多 20 局，按需调大）。"""
    try:
        limit = max(1, min(200, int((value or {}).get('limit') or 20)))
    except (TypeError, ValueError):
        limit = 20
    coverage = official_coverage()
    index = _camp_official_index()
    entries = [index[item['gameSeq']] for item in coverage['sample']
               if item['gameSeq'] in index]
    if not entries:
        return {'ok': True, 'report': {'tried': 0, 'imported': 0, 'attached': 0,
                                       'skipped': 0, 'failed': 0, 'items': []},
                'coverage': coverage}
    report = _camp_auto_official(entries, limit=limit, actor='backfill')
    _invalidate_v3_snapshot()
    return {'ok': True, 'report': report, 'coverage': official_coverage()}


@app.get('/api/official/replays/{replay_id}')
def get_official_replay(replay_id: str):
    try:
        meta, normalized = camp_replay.read_normalized(replay_id)
    except camp_replay.CampReplayError as error:
        raise HTTPException(404, str(error))
    return {'meta': meta, 'normalized': normalized}


@app.get('/api/official/replays/{replay_id}/positions')
def get_official_positions(replay_id: str):
    try:
        path = camp_replay.positions_path(replay_id)
    except camp_replay.CampReplayError as error:
        raise HTTPException(404, str(error))
    if not path:
        raise HTTPException(404, '该官方回放没有位置文件')
    return FileResponse(path)


# ---- Camp login-state sync: an authorized coach account pulls per-player details ----

CAMP_CONFIG_PATH = Path(os.environ.get('CAMP_CONFIG_FILE', DATA_DIR / 'camp_config.json'))
_camp_sync_lock = threading.Lock()
_camp_sync_job = {'running': False, 'result': None, 'error': None,
                  'startedAt': None, 'finishedAt': None,
                  'progress': {'done': 0, 'total': 0, 'current': '', 'phase': ''}}


def _camp_tools():
    tools = ROOT / 'tools'
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))


_GAME_SEQ_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _safe_game_seq(value) -> str:
    """营地对局 ID 只允许单段安全字符，避免拼路径时穿越到其它目录。"""
    text = str(value or '').strip()
    if not text or text in ('.', '..') or not _GAME_SEQ_RE.match(text):
        return ''
    return text


def _camp_detail_path(game_seq: str) -> Path:
    """营地详情落盘位置以 camp_sync 的 DETAIL_DIR 为准。

    camp_sync 支持 CAMP_DETAIL_DIR，演示实例也可能用 KPL_DATA_DIR 指向隔离库；
    写死 DATA_DIR/camp_details 会让同步写在一处、建通道读另一处。
    """
    _camp_tools()
    import camp_sync
    seq = _safe_game_seq(game_seq)
    if not seq:
        raise ValueError(f'营地对局 ID 非法：{game_seq!r}')
    return camp_sync.DETAIL_DIR / f'{seq}.json'


AUTO_REVIEWER = '营地自动同步'


def _invalidate_v3_snapshot() -> None:
    """自动入库发生在后台线程/GET 里，中间件不会替我们刷新 V3 快照。"""
    if V3_MODULE is not None:
        try:
            V3_MODULE.invalidate_snapshot()
        except Exception:
            pass


def _write_channel_bundle(channel: dict) -> dict:
    """把通道写成正式比赛 bundle；调用方负责标记 review 与落库。"""
    data = channel_store.bundle(channel)
    folder = MATCHES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'channel-{channel["id"]}.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    channel['saved'] = {'status': 'saved', 'bundleKey': data['match']['key'],
                        'savedAt': channel_store.now()}
    return data


def _refresh_saved_bundle_official(channel: dict) -> bool:
    """把后挂上的官方回放补进已入库 bundle，不改动其余终局数据。

    挂回放时通道会以 unreviewed 结束（来源变化需要重新复核），不能直接调用
    ``channel_store.bundle`` 重算整包；这里只补时间轴与 officialReplay 元数据，
    这样旧对局不必重新入库也能恢复脉搏/阶段分析。
    """
    if (channel.get('saved') or {}).get('status') != 'saved':
        return False
    path = MATCHES_DIR / f'channel-{channel["id"]}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    official = channel.get('official') or {}
    timeline = official_economy.timeline(official)
    if not timeline:
        return False
    team = data.setdefault('team', {})
    previous = team.get('timeline') or []
    if previous and not team.get('recordingTimeline'):
        team['recordingTimeline'] = previous
    team['timeline'] = timeline
    team['timelineSource'] = 'official-30s'
    official_match = official.get('match') or {}
    official_positions = official.get('positions') or {}
    data.setdefault('match', {})['officialReplay'] = {
        'id': official.get('id'), 'kind': official.get('kind'),
        'winCamp': official_match.get('winCamp'),
        'teams': official_match.get('teams'), 'score': official_match.get('score'),
        'teamGold': official_match.get('teamGold'),
        'goldPoints': official_match.get('goldPoints'),
        'goldIntervalSecApprox': official_match.get('goldIntervalSecApprox'),
        'events': official_match.get('keyEvents'),
        'positions': {'perSecond': official_positions.get('perSecond'),
                      'pointsPerPlayer': official_positions.get('pointsPerPlayer'),
                      'file': official_positions.get('file')},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


def _approve_channel(channel: dict, reviewer: str = AUTO_REVIEWER, notes: str = '',
                     allow_missing: bool = False) -> dict:
    """复核并写入正式统计；有缺失值时默认拒绝，除非明确确认。"""
    draft = channel.get('draft') or {}
    missing = draft.get('missing') or []
    if missing and not allow_missing:
        return {'ok': False, 'missing': missing, 'error': '存在缺失值，需逐条确认'}
    labels = '、'.join(f'{item.get("label")}缺{item.get("missing")}/10' for item in missing)
    default_notes = ('营地数据完整，自动通过' if not missing
                     else f'确认缺失后通过：{labels}')
    channel_store.set_review(channel, reviewer or AUTO_REVIEWER, notes or default_notes)
    data = _write_channel_bundle(channel)
    return {'ok': True, 'bundleKey': data['match']['key'], 'missing': missing}


def _clean_camp_players(players) -> list:
    cleaned = []
    for player in players if isinstance(players, list) else []:
        if not isinstance(player, dict):
            continue
        camp_id = str(player.get('campUserId') or '').strip()
        if not camp_id.isdigit():
            continue
        item = {'nickname': str(player.get('nickname') or '').strip()[:40],
                'campUserId': camp_id}
        # 离队的号不必删除：取消勾选就不再拉取，历史数据还留着。
        if 'enabled' in player:
            item['enabled'] = bool(player.get('enabled'))
        cleaned.append(item)
    return cleaned


def _camp_config_read() -> dict:
    try:
        value = json.loads(CAMP_CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'players': []}
    return {'players': _clean_camp_players(value.get('players'))}


def _camp_auto_attach(game_seqs):
    """同步完成后，把新入库的营地详情自动挂到已关联同局官方回放的通道。"""
    attached = []
    with db() as c:
        rows = c.execute('SELECT id, body FROM channels').fetchall()
    channels = []
    for row in rows:
        try:
            channels.append(json.loads(row['body']))
        except (TypeError, ValueError):
            continue
    for game_seq in game_seqs:
        target = next((channel for channel in channels
                       if (channel.get('official') or {}).get('id') == f'camp-{game_seq}'
                       and not ((channel.get('sources') or {}).get('camp') or {}).get('players')), None)
        if target is None:
            continue
        try:
            _camp_attach_to_channel(target, game_seq)
            with db() as c:
                _save_channel(c, target)
            attached.append({'channelId': target.get('id'), 'gameSeq': game_seq})
        except Exception:
            continue  # 单通道失败不影响其他
    return attached


def _camp_official_index():
    """本地已同步的战局清单 → {gameSeq: 列表条目}，供补拉官方回放用。

    `morebattlelist` 的每一条自带 gameSvrId / relaySvrId，够拼出
    battleanalyze 的请求体；营地详情（battledetail）里没有这两个字段，
    所以只能从清单取。清单每次同步都会覆盖，保留最近约 40 局。
    """
    index = {}
    folder = DATA_DIR / 'camp_lists'
    if not folder.is_dir():
        return index
    for path in folder.glob('*.json'):
        try:
            items = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            seq = str(entry.get('gameSeq') or '')
            if seq and seq not in index:
                index[seq] = entry
    return index


def _camp_auto_official(entries, limit=40, actor='camp-sync', camp_user_id=''):
    """营地同步之后，用清单里的服务器参数直接把官方回放拉下来并挂到通道。

    设计上「只给一个营地链接就该自动爬回放」，但这一步此前根本没接：
    前端从未调用 `/api/official/replay`，同步流程也只写入口径里的
    `official.source` 而没有真正下载。这里补上，失败只记原因，不打断同步。

    `playerid` 的来源只有两处：`data/camp_lists/` 里原始列表条目的
    `analyseUrl`，或调用方传进来的营地账号 ID（`camp_user_id`）。
    采集页同步回的条目是 `/api/camp/list` 裁剪过的，没有 `analyseUrl`；
    清单缓存又只有命令行工具会写，所以这里必须把账号 ID 带上，否则
    每条都会以「没有可用的 playerid」失败（营地同步成功、回放永远为空）。
    """
    index = _camp_official_index()
    by_seq = {}
    with db() as c:
        rows = c.execute('SELECT id, body FROM channels').fetchall()
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        official_id = str((channel.get('official') or {}).get('id') or '')
        if official_id.startswith('camp-'):
            by_seq.setdefault(official_id[5:], channel)

    report = {'tried': 0, 'imported': 0, 'attached': 0, 'skipped': 0,
              'failed': 0, 'items': []}
    for entry in entries or []:
        if report['tried'] >= limit:
            break
        seq = str((entry or {}).get('gameSeq') or '')
        if not seq:
            continue
        folder = camp_replay.STORE / f'camp-{seq}'
        if (folder / 'meta.json').is_file():
            report['skipped'] += 1
            continue
        source = index.get(seq) or entry
        if not (source.get('gameSvrId') and source.get('relaySvrId')):
            report['failed'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'failed',
                                    'error': '清单里没有 gameSvrId / relaySvrId'})
            continue
        report['tried'] += 1
        # 兜底：调用方漏传营地 ID 时，从条目自带的归属 ID 取（前端按它分组）。
        owner_id = camp_user_id or str(source.get('ownerCampUserId') or '')
        try:
            result = camp_replay.import_entry(source, force=False,
                                              camp_user_id=owner_id)
        except camp_replay.CampReplayError as error:
            report['failed'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'failed', 'error': str(error)})
            continue
        except Exception as error:  # 网络/磁盘
            report['failed'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'failed',
                                    'error': f'{type(error).__name__}: {error}'})
            continue
        report['imported'] += 1
        channel = by_seq.get(seq)
        if channel is None:
            report['items'].append({'gameSeq': seq, 'status': 'imported',
                                    'error': '还没有对应的采集通道，回放已单独落盘'})
            continue
        try:
            meta, normalized = camp_replay.read_normalized(result['id'])
            with db() as c:
                channel_store.attach_official(channel, result['id'], meta, normalized, actor)
                _refresh_saved_bundle_official(channel)
                _save_channel(c, channel, actor, 'official-auto')
            report['attached'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'attached', 'error': ''})
        except Exception as error:
            report['failed'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'imported',
                                    'error': f'回放已落盘但挂载失败：{error}'})
    return report


def _camp_entry_match(entry: dict, nickname: str) -> dict:
    """把一条营地列表记录翻成采集通道的可读对局信息。

    采集流水以前只有「对手未标注 / 没有更多字段」：入库只写了详情 JSON，
    没建通道。这里把教练一眼要认的信息写进 match，让流水能直接讲清这把。
    """
    seq = str(entry.get('gameSeq') or '')
    started = str(entry.get('startedAt') or '')
    gametime = str(entry.get('gametime') or '')
    date = str(entry.get('date') or (started[:10] if started else ''))
    # gametime 是 "MM-DD HH:MM"，没有年份；补成 ISO 便于筛选与排序。
    if not date and gametime:
        date = f'{time.localtime().tm_year}-{gametime[:5]}'
    result = int(entry.get('gameresult') or 0)
    own_camp = str(entry.get('acntCamp') or '')
    win_camp = str(entry.get('winCamp') or '')
    own_side = {'1': 'left', '2': 'right'}.get(own_camp, '')
    winner = {'1': 'left', '2': 'right'}.get(win_camp, '')
    if not winner and result in (1, 2) and own_side:
        other = 'right' if own_side == 'left' else 'left'
        winner = own_side if result == 1 else other
    try:
        from hero_catalog import hero_name
        hero = entry.get('heroName') or (hero_name(entry.get('heroId')) if entry.get('heroId') else None)
    except Exception:
        hero = entry.get('heroName')
    kda = [entry.get('killcnt'), entry.get('deadcnt'), entry.get('assistcnt')]
    return {
        'date': date,
        'opponent': str(entry.get('opponent') or ''),
        'session': '', 'version': '',
        'mode': str(entry.get('mapName') or ''),
        'durationSec': int(entry.get('usedTime') or 0) or None,
        'scores': {'left': None, 'right': None},
        'ownSide': own_side, 'winner': winner,
        'startedAt': started, 'gametime': gametime,
        'gameSeq': seq, 'campUserId': str(entry.get('ownerCampUserId') or ''),
        'ownerName': nickname or '', 'heroName': hero or '',
        'heroIcon': entry.get('heroIcon') or '',
        'kda': kda, 'gameresult': result,
        'gradeGame': entry.get('gradeGame'),
        'desc': str(entry.get('desc') or ''),
        'roleJobName': str(entry.get('roleJobName') or ''),
    }


def _camp_ensure_channels(entries, nickname: str, progress=None) -> dict:
    """每拉到一局详情就建/补一条采集通道，并挂上十人面板。

    按 official.id = camp-<gameSeq> 去重；已有通道只补齐空字段，不覆盖教练
    手工填的对手 / 训练组 / 版本。单个通道失败不影响其它局。
    """
    with db() as c:
        rows = c.execute('SELECT id, body FROM channels').fetchall()
    by_seq = {}
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        official_id = str((channel.get('official') or {}).get('id') or '')
        if official_id.startswith('camp-'):
            by_seq[official_id[5:]] = channel

    report = {'created': 0, 'updated': 0, 'attached': 0, 'saved': 0,
              'review': 0, 'failed': 0, 'skipped': 0, 'channelIds': [], 'items': []}
    total = len(entries)
    saved_any = False
    for index, entry in enumerate(entries, 1):
        seq = _safe_game_seq((entry or {}).get('gameSeq'))
        if not seq:
            report['failed'] += 1
            report['items'].append({'gameSeq': str((entry or {}).get('gameSeq') or ''),
                                    'status': 'failed',
                                    'error': '列表条目没有合法对局 ID'})
            continue
        if progress:
            progress(index, total, seq, 'channel')
        # 详情没拉到就不建审查记录：没有十人面板的通道只会把缺失值审查区堆满，
        # 教练也补不出内容。这局继续留在拉取列表里，下次可以重试。
        if not _camp_detail_path(seq).is_file():
            report['skipped'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'skipped',
                                    'error': '营地详情没拉到'})
            continue
        info = _camp_entry_match(entry, nickname)
        channel = by_seq.get(seq)
        if channel is None:
            channel = channel_store.blank(info)
            # blank() 的 match 只留白名单字段；把「这把是什么」的补充信息写回，
            # 采集流水才不会只剩「对手未标注 / 没有更多字段」。
            channel['match'].update({key: value for key, value in info.items()
                                     if key not in ('scores', 'opponent', 'session', 'version')})
            channel['id'] = uuid.uuid4().hex
            channel['_createdAt'] = time.time()
            channel['official'] = {
                'id': f'camp-{seq}', 'schema': 'camp-replay-v1', 'kind': 'personal',
                'source': {'gameSeq': seq,
                           'gameSvr': str(entry.get('gameSvrId') or ''),
                           'relaySvr': str(entry.get('relaySvrId') or ''),
                           'playerId': str(entry.get('uniqueRoleId') or '')},
            }
            channel_store.append_log(channel, 'create', 'camp-sync', {'gameSeq': seq})
            report['created'] += 1
        else:
            # 只补空字段；教练录入过的对手 / 训练组 / 版本一律保留。
            match = channel.setdefault('match', {})
            for key, value in info.items():
                if key in ('opponent', 'session', 'version'):
                    continue
                if not match.get(key) and value not in (None, '', 0):
                    match[key] = value
            report['updated'] += 1
        detail_path = _camp_detail_path(seq)
        already_parsed = bool((channel.get('sources') or {}).get('camp', {}).get('players'))
        if detail_path.is_file() and not already_parsed:
            try:
                detail = json.loads(detail_path.read_text(encoding='utf-8'))
                channel_store.attach_camp_detail(channel, seq, detail, None, 'camp-sync')
                report['attached'] += 1
            except Exception:
                # 详情结构不完整时仍保留通道与列表信息，后续可重试。
                pass
        try:
            with db() as c:
                _save_channel(c, channel, 'camp-sync')
            report['channelIds'].append(channel.get('id'))
            by_seq[seq] = channel
        except Exception as error:
            report['failed'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'failed',
                                    'error': f'写入通道失败：{error}'})
            continue
        # 已经写入正式统计的局不再重复自动通过，避免覆盖教练的复核备注。
        if (channel.get('saved') or {}).get('status') == 'saved':
            report['items'].append({'gameSeq': seq, 'status': 'saved', 'error': '',
                                    'alreadySaved': True})
            continue
        # 营地同步完成且十人面板无缺失：直接进入正式统计，不再强制人工复核。
        missing = (channel.get('draft') or {}).get('missing') or []
        if missing:
            report['review'] += 1
            labels = '、'.join(f'{item.get("label")}缺{item.get("missing")}/10' for item in missing)
            report['items'].append({'gameSeq': seq, 'status': 'review',
                                    'error': f'缺 {labels}'})
            continue
        try:
            _approve_channel(channel, AUTO_REVIEWER)
            with db() as c:
                _save_channel(c, channel, AUTO_REVIEWER, 'auto-approve')
            report['saved'] += 1
            saved_any = True
            report['items'].append({'gameSeq': seq, 'status': 'saved', 'error': ''})
        except Exception as error:
            # 缺必采材料等无法直接入库的情况仍留在审查区，不阻塞其它局。
            report['review'] += 1
            report['items'].append({'gameSeq': seq, 'status': 'review',
                                    'error': f'没能写入正式统计：{error}'})
    if saved_any:
        _invalidate_v3_snapshot()
    return report


def _camp_entry_from_detail(game_seq: str, body: dict, nickname: str = '') -> dict:
    """把已落盘的营地详情还原成列表条目，供旧数据补建采集通道。"""
    data = body.get('data') or {}
    head = data.get('head') or {}
    entry = dict(body.get('_campEntry') or {})
    entry['gameSeq'] = str(game_seq)
    entry['mapName'] = entry.get('mapName') or head.get('mapName') or '营地对局'
    times = camp_times(body)
    if times:
        entry.update({key: times[key] for key in ('startedAt', 'eventAt', 'date') if times.get(key)})
    entry['killcnt'] = head.get('killCnt', entry.get('killcnt'))
    entry['deadcnt'] = head.get('deadCnt', entry.get('deadcnt'))
    entry['assistcnt'] = head.get('assistCnt', entry.get('assistcnt'))
    entry['heroId'] = head.get('heroId')
    entry['heroName'] = head.get('heroName')
    entry['gradeGame'] = head.get('gradeGame')
    entry['desc'] = head.get('matchDesc') or ''
    own_camp = str(head.get('acntCamp') or '')
    entry['AcntCamp'] = own_camp
    entry['acntCamp'] = own_camp
    result = head.get('gameResult')
    if result is True or str(result).lower() in ('true', '1'):
        entry['gameresult'] = 1
    elif result is False or str(result).lower() in ('false', '0'):
        entry['gameresult'] = 2
    if own_camp in ('1', '2') and 'gameresult' in entry:
        entry['winCamp'] = own_camp if entry['gameresult'] == 1 else ('2' if own_camp == '1' else '1')
    entry['ownerCampUserId'] = str(head.get('userId') or '')
    entry['uniqueRoleId'] = str(head.get('playerId') or head.get('roleId') or '')
    entry['ownerName'] = nickname
    # 本人英雄图标 / 分路从十人面板补；没有也不影响建通道。
    player_id = str(head.get('playerId') or '')
    for role in (data.get('blueRoles') or []) + (data.get('redRoles') or []):
        basic = role.get('basicInfo') or {}
        if str(basic.get('playerId') or '') != player_id:
            continue
        records = role.get('battleRecords') or {}
        used = records.get('usedHero') or {}
        entry['heroIcon'] = used.get('heroIcon') or ''
        try:
            from bp_camp import POSITION_LANES
            entry['roleJobName'] = POSITION_LANES.get(int(records.get('position'))) or ''
        except (TypeError, ValueError, KeyError, ImportError):
            entry['roleJobName'] = ''
        break
    return entry


_camp_backfill_lock = threading.Lock()
_camp_backfill_state = {'at': 0.0}


def _camp_backfill_channels() -> dict:
    """为「只有详情、没有通道」的旧数据补建采集通道。

    历史版本同步只落 camp_details/*.json，导致采集流水为空。这里在状态读取
    时做一次幂等补建；通道已存在的局直接跳过，不覆盖教练录入的信息。
    """
    now = time.time()
    if now - float(_camp_backfill_state.get('at') or 0) < 30:
        return {'created': 0}
    if not _camp_backfill_lock.acquire(blocking=False):
        return {'created': 0}
    try:
        _camp_backfill_state['at'] = now
        _camp_tools()
        import camp_sync
        detail_dir = camp_sync.DETAIL_DIR
        if not detail_dir.is_dir():
            return {'created': 0}
        details = {path.stem: path for path in detail_dir.glob('*.json')}
        if not details:
            return {'created': 0}
        with db() as c:
            rows = c.execute('SELECT body FROM channels').fetchall()
        channeled = set()
        for row in rows:
            try:
                official_id = str((json.loads(row['body']).get('official') or {}).get('id') or '')
            except (TypeError, ValueError):
                continue
            if official_id.startswith('camp-'):
                channeled.add(official_id[5:])
        missing = sorted(set(details) - channeled)
        if not missing:
            return {'created': 0}
        nicknames = {player['campUserId']: player.get('nickname') or ''
                     for player in _camp_config_read().get('players') or []}
        groups = {}
        for seq in missing:
            try:
                body = json.loads(details[seq].read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            entry = _camp_entry_from_detail(seq, body)
            owner = entry.get('ownerCampUserId') or ''
            entry['ownerCampUserId'] = owner
            groups.setdefault(owner, []).append((entry, body))
        created = 0
        saved = 0
        review = 0
        for owner, items in groups.items():
            entries = [entry for entry, _body in items]
            if any(entry.get('ownerName') for entry in entries):
                nickname = next(entry['ownerName'] for entry in entries if entry.get('ownerName'))
            else:
                nickname = nicknames.get(owner, '')
            report = _camp_ensure_channels(entries, nickname)
            created += int(report.get('created') or 0)
            saved += int(report.get('saved') or 0)
            review += int(report.get('review') or 0)
        return {'created': created, 'saved': saved, 'review': review,
                'scanned': len(missing)}
    except Exception:
        return {'created': 0}
    finally:
        _camp_backfill_lock.release()


_camp_finalize_lock = threading.Lock()
_camp_finalize_state = {'at': 0.0}


def _camp_auto_finalize_channels() -> dict:
    """把营地通道里无缺失值的局补送进正式统计。

    旧数据已经建了通道但还停在「待复核」；这里做一次幂等自动通过，
    有缺失值的局保持不动，交给缺失值审查逐条确认。
    """
    now = time.time()
    if now - float(_camp_finalize_state.get('at') or 0) < 15:
        return {'passed': 0, 'skipped': 0}
    if not _camp_finalize_lock.acquire(blocking=False):
        return {'passed': 0, 'skipped': 0}
    try:
        _camp_finalize_state['at'] = now
        with db() as c:
            rows = c.execute('SELECT id, body FROM channels').fetchall()
        passed, skipped = [], 0
        for row in rows:
            try:
                channel = json.loads(row['body'])
            except (TypeError, ValueError):
                continue
            official_id = str((channel.get('official') or {}).get('id') or '')
            if not official_id.startswith('camp-'):
                continue
            if (channel.get('saved') or {}).get('status') == 'saved':
                continue
            try:
                channel_store.rebuild(channel)
            except Exception:
                skipped += 1
                continue
            missing = (channel.get('draft') or {}).get('missing') or []
            if missing:
                skipped += 1
                continue
            try:
                _approve_channel(channel, AUTO_REVIEWER)
                with db() as c:
                    _save_channel(c, channel, AUTO_REVIEWER, 'auto-approve')
                passed.append(channel.get('id'))
            except Exception:
                skipped += 1
        if passed:
            _invalidate_v3_snapshot()
        return {'passed': len(passed), 'skipped': skipped, 'channelIds': passed}
    finally:
        _camp_finalize_lock.release()


def _camp_sync_entries(camp_sync, camp_user_id: str, entries, on_progress=None):
    """调用 camp_sync 拉详情；兼容不带 on_progress 的旧版 tools。

    升级包只覆盖主程序、tools/ 还是旧版时（现场就出现过），多传一个
    on_progress 会抛 TypeError 直接把整批同步打断；这里退化成无进度拉取，
    进度条退回到「按条目估算」，但数据照常入库。
    """
    try:
        return camp_sync.sync_entries(camp_user_id, entries, on_progress=on_progress)
    except TypeError as error:
        if 'on_progress' not in str(error):
            raise
        return camp_sync.sync_entries(camp_user_id, entries)


def _camp_sync_worker(camp_user_id: str, nickname: str, entries):
    _camp_tools()
    import camp_sync

    def progress(done, total, current, phase):
        with _camp_sync_lock:
            _camp_sync_job['progress'] = {'done': done, 'total': total,
                                          'current': current, 'phase': phase}

    summary = None
    try:
        summary = _camp_sync_entries(camp_sync, camp_user_id, entries, progress)
        # 入库即建采集通道：以前只写 camp_details/*.json，采集流水与统计都是空的。
        channels = _camp_ensure_channels(entries, nickname, progress)
        # 只给一条营地链接 → 详情、通道、官方回放一起到位。回放拉取放在通道之后，
        # 这样拉下来的经济曲线/事件/位置能立刻挂到通道上。
        try:
            channels['official'] = _camp_auto_official(
                entries, actor='camp-sync', camp_user_id=camp_user_id)
        except Exception as error:
            channels['official'] = {'failed': 1, 'items': [],
                                    'error': f'{type(error).__name__}: {error}'}
        with _camp_sync_lock:
            _camp_sync_job['progress'] = {'done': max(1, len(entries)), 'total': max(1, len(entries)),
                                          'current': '', 'phase': 'done'}
        result = {'nickname': nickname or f'选手 {camp_user_id[-4:]}',
                  'campUserId': camp_user_id, 'ok': True, 'summary': summary,
                  'channels': channels}
    except BaseException as error:  # camp_sync 用 SystemExit 报致命错误
        auth_invalid = bool(getattr(error, 'auth_invalid', False))
        # 已经拉到本机的详情照样入库：网络中途断掉不该让前面这些局白拉。
        salvaged = None
        if not auth_invalid:
            try:
                salvaged = _camp_ensure_channels(entries, nickname)
            except Exception:
                salvaged = None
        with _camp_sync_lock:
            _camp_sync_job['progress'] = {**(_camp_sync_job.get('progress') or {}),
                                          'phase': 'error'}
        result = {'nickname': nickname or f'选手 {camp_user_id[-4:]}',
                  'campUserId': camp_user_id, 'ok': False,
                  'authInvalid': auth_invalid,
                  'reason': getattr(error, 'reason', '') if auth_invalid else '',
                  'stage': 'channel' if summary is not None else 'detail',
                  'error': f'{type(error).__name__}: {error}',
                  'channels': salvaged}
        return [result], (salvaged or {}).get('channelIds') or []
    return [result], channels['channelIds']


@app.get('/api/camp/auth')
def camp_auth_status():
    _camp_tools()
    import camp_auth
    return camp_auth.read_account()


AUTH_CHECK_TTL = 300


@app.post('/api/camp/auth/check')
def camp_auth_check(force: bool = False):
    """主动检测一次营地登录态，让「授权失效」在拉取前就显示出来。

    只发一次轻量列表请求：营地返回任何结构化响应（包括「用户不存在」这类
    业务错误）都说明登录态被接受；只有明确的登录态错误才记为失效。网络异常
    只返回「暂时无法检测」，不误伤本地凭证。
    """
    _camp_tools()
    import camp_auth
    import camp_client
    account = camp_auth.read_account()
    if not account.get('authorized'):
        return {'authorized': False, 'valid': False, 'reason': '还没有营地登录凭证。'}
    health = camp_auth.read_health()
    if not force and health.get('checkedAt'):
        try:
            checked = time.mktime(time.strptime(health['checkedAt'], '%Y-%m-%dT%H:%M:%S'))
        except (ValueError, OverflowError):
            checked = 0
        if time.time() - checked < AUTH_CHECK_TTL:
            return {'authorized': True, 'valid': not health['invalid'],
                    'reason': health['reason'], 'code': health['code'],
                    'checkedAt': health['checkedAt'], 'cached': True}
    if not account.get('userId'):
        return {'authorized': True, 'valid': None,
                'reason': '凭证缺少营地用户 ID，无法完成检测。'}
    try:
        camp_client.call('/game/morebattlelist', {
            'lastTime': 0, 'recommendPrivacy': 0, 'apiVersion': 5,
            'friendUserId': account['userId'], 'option': 0}, timeout=8)
    except camp_client.CampAuthError as error:
        # 即使异常不是本模块发起的，也把失效状态落下来，页面刷新后仍然能提示。
        camp_auth.mark_invalid(str(error), getattr(error, 'code', ''))
        current = camp_auth.read_health()
        return {'authorized': True, 'valid': False, 'reason': str(error),
                'code': getattr(error, 'code', ''), 'checkedAt': current['checkedAt'],
                'cached': False}
    except Exception as error:  # noqa: BLE001 - 网络/协议异常不当作授权失效
        return {'authorized': True, 'valid': None,
                'reason': f'暂时无法完成检测：{type(error).__name__}: {error}'}
    camp_auth.mark_checked(True)
    return {'authorized': True, 'valid': True, 'reason': '', 'code': '',
            'checkedAt': camp_auth.read_health()['checkedAt'], 'cached': False}


@app.post('/api/camp/auth/qr')
def camp_auth_qr():
    _camp_tools()
    import camp_auth
    try:
        return camp_auth.create_login_session()
    except Exception as error:
        raise HTTPException(502, f'获取登录二维码失败：{error}')


@app.get('/api/camp/auth/poll')
def camp_auth_poll(taskId: str):
    _camp_tools()
    import camp_auth
    try:
        return camp_auth.poll_login_once(taskId)
    except Exception as error:
        # 兜底：轮询接口永远返回结构化状态，避免前端把 500 当成「继续等待」。
        return {'status': 'error', 'message': f'轮询失败：{error}'}


@app.post('/api/camp/auth/clear')
def camp_auth_clear():
    _camp_tools()
    import camp_auth
    camp_auth.AUTH_PATH.unlink(missing_ok=True)
    camp_auth.reset_health()
    camp_auth.cancel_login_session()
    return {'ok': True}


@app.post('/api/camp/auth/cancel')
def camp_auth_cancel(taskId: str = ''):
    """放弃当前二维码（用户点「取消扫码」或退出重新扫时调用）。"""
    _camp_tools()
    import camp_auth
    camp_auth.cancel_login_session(taskId)
    return {'ok': True}


@app.post('/api/camp/resolve')
def camp_resolve(value: dict):
    """从营地分享链接/短链解析营地 ID，供选手白名单登记，免人工抄写。

    只看 userId：对局模式（含开房间征召）、页面路径和回放服务器参数都不影响结果。
    """
    _camp_tools()
    import camp_replay
    url = str(value.get('url') or '').strip()
    if not url:
        raise HTTPException(400, '请粘贴营地分享链接')
    try:
        if camp_replay.is_short_link(url):
            url = camp_replay.expand_short_link(url)
        info = camp_replay.extract_camp_user_id(url)
    except camp_replay.CampReplayError as error:
        raise HTTPException(400, str(error))
    return info


@app.get('/api/camp/config')
def camp_config_get():
    return _camp_config_read()


@app.post('/api/camp/config')
def camp_config_set(value: dict):
    players = _clean_camp_players(value.get('players'))
    CAMP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAMP_CONFIG_PATH.write_text(json.dumps({'players': players}, ensure_ascii=False, indent=1),
                                encoding='utf-8')
    return {'players': players}


@app.get('/api/camp/sync')
def camp_sync_status():
    _camp_tools()
    import camp_sync
    import camp_auth
    # 旧版本只落详情、不建通道：打开采集页时先幂等补建一次，
    # 让历史对局立刻出现在采集流水里，不用教练再手动入库一遍。
    backfill = {'created': 0}
    finalize = {'passed': 0, 'skipped': 0}
    if not _camp_sync_job.get('running'):
        backfill = _camp_backfill_channels()
        finalize = _camp_auto_finalize_channels()
    details = list(camp_sync.DETAIL_DIR.glob('*.json')) if camp_sync.DETAIL_DIR.is_dir() else []
    with db() as c:
        rows = c.execute('SELECT id, body FROM channels').fetchall()
    channel_by_game_seq = {}
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        official = channel.get('official') or {}
        if str(official.get('id') or '').startswith('camp-'):
            channel_by_game_seq[official['id'][5:]] = channel.get('id')
    detail_items = []
    for path in sorted(details, key=lambda item: item.stat().st_mtime, reverse=True)[:60]:
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        entry = body.get('_campEntry') or {}
        head = (body.get('data') or {}).get('head') or {}
        times = camp_times(body)
        detail_items.append({
            'gameSeq': path.stem,
            'mapName': entry.get('mapName') or head.get('mapName'),
            'gametime': entry.get('gametime'),
            'startedAt': times.get('startedAt'),
            'eventAt': times.get('eventAt'),
            'battleType': entry.get('battleType'),
            'winCamp': entry.get('winCamp'),
            'kda': [entry.get('killcnt'), entry.get('deadcnt'), entry.get('assistcnt')],
            'syncedAt': path.stat().st_mtime,
            'channelId': channel_by_game_seq.get(path.stem),
        })
    return {**_camp_sync_job, 'detailsCount': len(details),
            'details': detail_items, 'backfill': backfill, 'finalize': finalize,
            'config': _camp_config_read(), 'auth': camp_auth.read_account()}


@app.post('/api/camp/list')
def camp_list(value: dict):
    """拉取选手的可达对局列表（只读预览，不落盘），每条附已入库标记。"""
    _camp_tools()
    import camp_client
    import camp_sync
    camp_user_id = str(value.get('campUserId') or '').strip()
    if not camp_user_id.isdigit():
        raise HTTPException(400, '营地 ID 需为 5–15 位数字')
    # 每条都带上「这局是谁的」：前端同步时按 ownerCampUserId 分组，再把它作为
    # campUserId 传给 /api/camp/sync；缺了它自动补拉官方回放就拿不到 playerid，
    # 结果是「同步成功、进统计，但回放一直空」。
    nickname = next((player.get('nickname') or ''
                     for player in _camp_config_read().get('players', [])
                     if player.get('campUserId') == camp_user_id), '')
    try:
        result = camp_client.call('/game/morebattlelist', {
            'lastTime': int(value.get('lastTime') or 0),
            'recommendPrivacy': 0, 'apiVersion': 5,
            'friendUserId': camp_user_id, 'option': 0})
    except camp_client.CampAuthError as error:
        # detail 保持字符串：采集页按字符串显示，另外读 authInvalid 提前提示补充授权。
        return JSONResponse(status_code=401, content={
            'detail': str(error), 'authInvalid': True,
            'reason': getattr(error, 'reason', str(error)),
            'code': getattr(error, 'code', '')})
    except SystemExit as error:
        raise HTTPException(409, str(error))
    body = result.get('body') or {}
    if body.get('returnCode') not in (0, '0'):
        raise HTTPException(502, f"营地列表接口失败：{json.dumps(body, ensure_ascii=False)[:200]}")
    data = body.get('data') or {}
    if data.get('invisible'):
        raise HTTPException(403, '该选手隐藏了战绩：请其在营地隐私设置里对教练可见（白名单）或恢复公开')
    # 「库里已有」指采集流水里已有这条通道，而不是仅仅下载过详情：
    # 早期版本入库只写 camp_details/*.json 不建通道，若按详情文件判断，
    # 这些局会被禁用勾选，永远补不回采集流水。
    with db() as c:
        channel_rows = c.execute('SELECT body FROM channels').fetchall()
    channeled_seqs = set()
    ready_seqs = set()
    saved_seqs = set()
    for row in channel_rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        official_id = str((channel.get('official') or {}).get('id') or '')
        if not official_id.startswith('camp-'):
            continue
        seq = official_id[5:]
        channeled_seqs.add(seq)
        # 通道建了但十人面板没挂上（详情下载失败/结构不完整）时，
        # 仍允许重新勾选补详情，不能当成「已入库」把入口堵死。
        if (channel.get('sources') or {}).get('camp', {}).get('players'):
            ready_seqs.add(seq)
        if (channel.get('saved') or {}).get('status') == 'saved':
            saved_seqs.add(seq)

    entries = []
    for entry in data.get('list') or []:
        game_seq = str(entry.get('gameSeq') or '')
        # 时间统一按项目口径：dtEventTime 是「记录发送时间」(epoch 秒)，
        # 真实开赛时间 = 发送时间 − 本局时长，按北京时间输出。
        # 营地的 gametime（如 "11-04 22:55"）是同一时刻的文本，作为直接显示值。
        event_at, used = int(entry.get('dtEventTime') or 0), int(entry.get('usedTime') or 0)
        times = camp_times({'_campEntry': {'dtEventTime': event_at, 'usedTime': used}})
        result = int(entry.get('gameresult') or 0)
        # gameresult: 1=胜 2=负（以被查选手视角）。缺失时用 winCamp/AcntCamp 兜底。
        if result not in (1, 2):
            win_camp = str(entry.get('winCamp') or '')
            own_camp = str(entry.get('AcntCamp') or '')
            if win_camp and own_camp:
                result = 1 if win_camp == own_camp else 2
        hero_id = entry.get('heroId')
        try:
            from hero_catalog import hero_name
            hero = entry.get('heroName') or (hero_name(hero_id) if hero_id else None)
        except Exception:
            hero = entry.get('heroName')
        entries.append({
            'gameSeq': game_seq,
            # 归属信息：前端据此分组并把营地 ID 传给同步接口（自动补拉回放要用）。
            'ownerCampUserId': camp_user_id,
            'ownerName': nickname,
            'dtEventTime': event_at,
            'startedAt': times.get('startedAt'),
            'eventAt': times.get('eventAt'),
            'date': times.get('date'),
            'gametime': entry.get('gametime'),
            'usedTime': used,
            'mapName': entry.get('mapName'), 'battleType': entry.get('battleType'),
            'winCamp': entry.get('winCamp'), 'acntCamp': entry.get('AcntCamp'),
            'gameresult': result,
            'killcnt': entry.get('killcnt'), 'deadcnt': entry.get('deadcnt'),
            'assistcnt': entry.get('assistcnt'),
            'heroId': hero_id, 'heroName': hero, 'heroIcon': entry.get('heroIcon'),
            'gradeGame': entry.get('gradeGame'), 'desc': entry.get('desc'),
            'roleJobName': entry.get('roleJobName'),
            'gameSvrId': str(entry.get('gameSvrId') or ''),
            'relaySvrId': str(entry.get('relaySvrId') or ''),
            'uniqueRoleId': camp_sync.entry_role_id(entry),
            # 「已进统计」只看正式 bundle；通道已建但等缺失值审查的局
            # 不再重复拉详情，前端用 channelReady 单独标记。
            'imported': game_seq in saved_seqs,
            'channelExists': game_seq in channeled_seqs,
            'channelReady': game_seq in ready_seqs,
            'detailCached': bool(_safe_game_seq(game_seq) and _camp_detail_path(game_seq).is_file()),
            # 营地只保留最近一个月的战局详情；更早的局前端直接标「营地无详情」，
            # 不再让教练勾选后才发现拉不到（-30457）。
            'campDetailAvailable': not camp_sync.detail_expired(
                {'dtEventTime': event_at, 'usedTime': used}),
        })
    return {'entries': entries, 'hasMore': bool(data.get('hasMore')),
            'lastTime': data.get('lastTime'), 'gaming': data.get('gaming')}


@app.post('/api/camp/sync')
def camp_sync_start(value: dict):
    """两段式同步第二段：按教练勾选的对局条目拉取详情并落盘，随后自动挂载通道。"""
    entries = value.get('entries') if isinstance(value.get('entries'), list) else []
    entries = [entry for entry in entries if isinstance(entry, dict) and entry.get('gameSeq')]
    if any(not _safe_game_seq(entry.get('gameSeq')) for entry in entries):
        raise HTTPException(400, '对局 ID 非法')
    camp_user_id = str(value.get('campUserId') or '').strip()
    nickname = str(value.get('nickname') or '').strip()
    if not entries:
        raise HTTPException(400, '请先获取对局列表并勾选要拉取的局')
    with _camp_sync_lock:
        if _camp_sync_job['running']:
            raise HTTPException(409, '同步已在进行中')
        _camp_sync_job.update({'running': True, 'result': None, 'error': None,
                               'startedAt': time.time(), 'finishedAt': None,
                               'progress': {'done': 0, 'total': len(entries),
                                            'current': '', 'phase': 'detail'}})

    def worker():
        try:
            results, auto_attached = _camp_sync_worker(camp_user_id, nickname, entries)
            _camp_sync_job.update({'running': False,
                                   'result': {'players': results, 'autoAttached': auto_attached},
                                   'finishedAt': time.time()})
        except Exception as error:
            _camp_sync_job.update({'running': False,
                                   'error': f'{type(error).__name__}: {error}',
                                   'finishedAt': time.time()})

    threading.Thread(target=worker, daemon=True).start()
    return {'ok': True, 'count': len(entries)}


def _camp_attach_to_channel(channel: dict, game_seq: str, actor=None):
    """读取本机营地详情并映射进通道草稿（纯内存；落库由调用方负责）。

    官方十人（heroName）优先读本地 normalized 缓存（含 heroName 且不依赖网络）；
    公开接口的身份字段已脱敏，hero 按阵营+顺序在 attach_camp_detail 里对应。
    """
    detail_path = _camp_detail_path(game_seq)
    if not detail_path.is_file():
        raise ValueError('本机还没有这局的营地详情；请先在采集通道页完成同步')
    detail = json.loads(detail_path.read_text(encoding='utf-8'))
    official = channel.get('official') or {}
    official_id = official.get('id') or ''
    if official_id.startswith('camp-') and official_id[5:] != game_seq:
        raise ValueError(f'通道已关联的是对局 {official_id[5:]}，与营地详情 {game_seq} 不一致')
    official_players = None
    if official_id.startswith('camp-'):
        try:
            _, normalized = camp_replay.read_normalized(official_id)
            official_players = normalized.get('players') or []
        except Exception:
            official_players = None
    if official_players is None:
        source = official.get('source') or {}
        if source.get('gameSeq') and source.get('gameSvr') and source.get('relaySvr'):
            try:
                link = camp_replay.parse_link(
                    'https://camp.qq.com/h5/webdist/battle-replay/index.html?'
                    + url_parse.urlencode({'gameseq': source['gameSeq'],
                                           'gamesvrentity': source['gameSvr'],
                                           'relaysvrentity': source['relaySvr'],
                                           'playerid': source.get('playerId') or 'undefined'}))
                _, official_data = camp_replay.fetch(link)
                official_players = (official_data or {}).get('matchInfo') or []
            except Exception:
                official_players = None
    if official_players is None and official_id.startswith('camp-'):
        raw_path = camp_replay.STORE / official_id / 'raw.json'
        if raw_path.is_file():
            try:
                official_players = (json.loads(raw_path.read_text(encoding='utf-8'))
                                    .get('data') or {}).get('matchInfo') or []
            except (OSError, ValueError):
                official_players = None
    channel_store.attach_camp_detail(channel, game_seq, detail, official_players, actor)


@app.post('/api/channels/{channel_id}/camp')
def channel_attach_camp(channel_id: str, value: dict):
    game_seq = _safe_game_seq(value.get('gameSeq'))
    if not game_seq:
        raise HTTPException(400, '缺少或非法的对局 ID')
    with db() as c:
        channel = _load_channel(c, channel_id)
    try:
        _camp_attach_to_channel(channel, game_seq, value.get('actor'))
    except ValueError as error:
        raise HTTPException(400, str(error))
    with db() as c:
        _save_channel(c, channel, value.get('actor'))
    # 补挂详情后如果已经完整，按新策略直接进入正式统计。
    if not (channel.get('draft') or {}).get('missing'):
        try:
            _approve_channel(channel, str(value.get('actor') or AUTO_REVIEWER))
            with db() as c:
                _save_channel(c, channel, value.get('actor'), 'auto-approve')
        except Exception:
            pass
    return channel


@app.post('/api/channels/{channel_id}/official')
def channel_attach_official(channel_id: str, value: dict):
    official_id = value.get('officialId')
    if not isinstance(official_id, str) or not official_id:
        raise HTTPException(400, '缺少官方回放 ID')
    try:
        meta, normalized = camp_replay.read_normalized(official_id)
    except camp_replay.CampReplayError as error:
        raise HTTPException(404, str(error))
    with db() as c:
        channel = _load_channel(c, channel_id)
        channel_store.attach_official(channel, official_id, meta, normalized,
                                      value.get('actor'))
        # 已入库的局：挂回放后同步刷新 bundle，否则脉搏/阶段会一直空着。
        _refresh_saved_bundle_official(channel)
        _save_channel(c, channel, value.get('actor'))
        return channel


# ---------------------------------------------------------------------------
# Recording library: original video, OCR report and evidence frames

def _recording_runner(recording_id, fps, engine):
    def runner(job):
        try:
            path = recording_store.video_path(recording_id)
            evidence = recording_store.evidence_dir(recording_id)
            recording_store.update_meta(
                recording_id, status='running', stage='准备识别', progress=1,
                engine=engine, sampleFps=fps, error=None)

            def progress(done, total):
                job.check_cancelled()
                percent = min(72, int(done / max(total, 1) * 72))
                stage = f'采样识别 {done}/{int(total)} 秒'
                job.stage(stage, percent)
                recording_store.set_progress(recording_id, stage, percent)

            report = video_ocr.analyze_video(
                str(path), fps=fps, progress=progress, evidence_dir=str(evidence))
            if engine in ('mimo', 'auto'):
                job.stage('Mimo 精读加载页与记分板', 78)
                report = video_mimo.refine_report(
                    report, str(evidence),
                    on_stage=lambda stage: job.stage(stage, 88))
            job.stage('保存识别报告', 96)
            recording_store.save_report(recording_id, report, engine, fps)
            return {'recordingId': recording_id, 'engine': engine,
                    'warnings': len(report.get('warnings') or [])}
        except ocr_jobs.JobCancelled:
            recording_store.update_meta(recording_id, status='cancelled',
                                        stage='已取消', error=None)
            raise
        except Exception as error:  # noqa: BLE001 - persist the failure beside the video
            recording_store.update_meta(recording_id, status='error',
                                        stage='识别失败', error=str(error))
            raise
    return runner


@app.post('/api/recordings')
async def upload_recording(request: Request, name: str = '录屏.mp4'):
    free = recording_store.free_bytes()
    if free < 256 * 1024 * 1024:
        raise HTTPException(
            507, f'本机录屏目录剩余空间不足 256 MB（当前 {free // (1024 ** 2)} MB）；'
                 '请清理磁盘，或把 KPL_RECORDINGS 指向空间更充足的目录。')
    temp = recording_store.new_temp_path()
    length = 0
    try:
        with open(temp, 'wb') as handle:
            async for chunk in request.stream():
                length += len(chunk)
                if length > recording_store.MAX_BYTES:
                    raise HTTPException(413, '录像文件超过本机上限')
                handle.write(chunk)
        return recording_store.finalize(temp, name)
    except recording_store.RecordingError as error:
        raise HTTPException(400, str(error))
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


@app.get('/api/recordings')
def list_recordings():
    return {'recordings': recording_store.list_recordings(),
            'stats': recording_store.library_stats(),
            'jobs': ocr_jobs.list_jobs(kind='recording', limit=20)}


@app.get('/api/recordings/{recording_id}')
def get_recording(recording_id: str):
    try:
        return {'recording': recording_store.read_meta(recording_id)}
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))


@app.get('/api/recordings/{recording_id}/report')
def get_recording_report(recording_id: str):
    try:
        return recording_store.read_report(recording_id)
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))


@app.get('/api/recordings/{recording_id}/evidence/{name}')
def get_recording_evidence(recording_id: str, name: str):
    try:
        path = recording_store.evidence_path(recording_id, name)
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))
    return FileResponse(path)


@app.delete('/api/recordings/{recording_id}')
def delete_recording(recording_id: str):
    if ocr_jobs.find_active('recording', recording_id):
        raise HTTPException(409, '该录像正在识别，请先取消任务')
    try:
        recording_store.delete(recording_id)
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))
    return {'ok': True}


@app.post('/api/recordings/{recording_id}/ocr')
def ocr_recording(recording_id: str, fps: float = 1.0, engine: str = 'mimo', force: bool = False):
    if not 0.2 <= fps <= 2:
        raise HTTPException(400, '采样帧率需在 0.2–2 之间')
    engine = str(engine or 'mimo').lower()
    if engine not in ('mimo', 'rapid', 'auto'):
        raise HTTPException(400, '识别引擎需为 mimo、rapid 或 auto')
    try:
        meta = recording_store.read_meta(recording_id)
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))
    if (meta.get('report') or {}).get('available') and not force:
        raise HTTPException(409, '已有识别报告；重新识别请传 force=true')
    active = ocr_jobs.find_active('recording', recording_id)
    if active:
        return active
    recording_store.update_meta(recording_id, status='queued', stage='排队中',
                                progress=0, engine=engine, sampleFps=fps, error=None)
    return ocr_jobs.submit('recording', recording_id,
                           _recording_runner(recording_id, fps, engine),
                           meta={'recordingId': recording_id, 'fps': fps, 'engine': engine})



def _load_channel(c, channel_id):
    row = c.execute('SELECT * FROM channels WHERE id=?', (channel_id,)).fetchone()
    if not row:
        raise HTTPException(404, '采集通道不存在')
    channel = json.loads(row['body'])
    channel['revision'] = row['revision']
    channel['sourceStatus'] = channel_store.source_status(channel)
    return channel


def _save_channel(c, channel, actor=None, action=None):
    if action:
        channel_store.append_log(channel, action, actor)
    old = c.execute('SELECT revision FROM channels WHERE id=?', (channel['id'],)).fetchone()
    revision = (old['revision'] + 1) if old else 1
    channel['revision'] = revision
    now = time.time()
    c.execute('INSERT INTO channels(id,revision,body,created_at,updated_at) VALUES(?,?,?,?,?) '
              'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, body=excluded.body, updated_at=excluded.updated_at',
              (channel['id'], revision, json.dumps(channel, ensure_ascii=False), channel.get('_createdAt') or now, now))
    return channel


def _channel_summary(channel, recordings=None):
    sources = channel.get('sources') or {}
    screenshot = sources.get('screenshot') or {}
    video = sources.get('video') or {}
    entry = channel.get('entry') or {}
    # 录像身份不能只看视频 sha：旧流程挂的是报告 JSON 的 sha/name，
    # 这里按 id/sha/文件名三线索映射回本地录像，页面才能标「已补采」。
    known_recordings = recording_store.identities(recordings)
    recording_ids = []
    for file in video.get('files') or []:
        matched = recording_store.match_file(file, known_recordings)
        if matched and matched not in recording_ids:
            recording_ids.append(matched)
    return {
        'id': channel.get('id'), 'revision': channel.get('revision'),
        # 录入方式与已用素材，供前端标记「这组素材已经补采过」、避免重复建档。
        'entry': {'mode': channel_store.entry_mode(channel),
                  'primary': str(entry.get('primary') or '')},
        'match': channel.get('match') or {}, 'sourceStatus': channel_store.source_status(channel),
        'coverage': (channel.get('draft') or {}).get('coverage') or {},
        'missing': (channel.get('draft') or {}).get('missing') or [],
        'review': channel.get('review') or {}, 'saved': channel.get('saved') or {},
        'screenshotImageIds': [str(value) for value in screenshot.get('imageIds') or []],
        'recordingShas': [str(file.get('sha256')) for file in video.get('files') or []
                          if file.get('sha256')],
        'recordingIds': recording_ids,
        'updatedAt': channel.get('updatedAt'), 'changeLog': channel.get('changeLog') or [],
    }


@app.get('/api/channels')
def channels_list():
    # 录像库只读一遍，避免每条通道都重复扫盘。
    recordings = recording_store.list_recordings()
    with db() as c:
        rows = c.execute('SELECT * FROM channels ORDER BY updated_at DESC').fetchall()
    result = []
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        channel['revision'] = row['revision']
        result.append(_channel_summary(channel, recordings))
    return {'schema': channel_store.SCHEMA, 'channels': result}


@app.post('/api/channels')
def channel_create(value: dict):
    match = value.get('match') if isinstance(value.get('match'), dict) else value
    if not any(str(match.get(key) or '').strip() for key in ('date', 'opponent', 'session')):
        raise HTTPException(400, '请至少填写比赛日期、对手或训练分组')
    entry = value.get('entry')
    channel = channel_store.blank(match)
    if entry is not None:
        if not isinstance(entry, dict):
            raise HTTPException(400, '录入方式格式错误：应为 {"mode": "camp" 或 "ocr"}')
        mode = str(entry.get('mode') or '').strip().lower()
        if mode not in channel_store.ENTRY_MODES:
            raise HTTPException(400, '录入方式只能是 camp（王者营地同步）或 ocr（截图/录屏录入）')
        channel['entry'] = {'mode': mode, 'primary': str(entry.get('primary') or '').strip()}
    channel['id'] = uuid.uuid4().hex
    channel['_createdAt'] = time.time()
    channel_store.append_log(channel, 'create', value.get('actor'), {'match': channel.get('match')})
    with db() as c:
        _save_channel(c, channel)
    return channel


@app.get('/api/channels/{channel_id}')
def channel_get(channel_id: str):
    with db() as c:
        return _load_channel(c, channel_id)


@app.patch('/api/channels/{channel_id}')
def channel_update(channel_id: str, value: dict):
    try:
        with db() as c:
            channel = _load_channel(c, channel_id)
            if isinstance(value.get('match'), dict):
                channel_store.update_match(channel, value['match'], value.get('actor'))
            if isinstance(value.get('review'), dict):
                channel_store.set_review(channel, value['review'].get('reviewedBy'),
                                          value['review'].get('notes'), value.get('actor'))
            _save_channel(c, channel, value.get('actor'), 'update')
            return channel
    except ValueError as error:
        raise HTTPException(400, str(error))


def _postgame_results(c, image_ids):
    """按选定顺序取分页识别结果；缺结果的图片给可操作提示。"""
    ids = [str(value) for value in image_ids]
    if not ids:
        raise HTTPException(400, '请选择同一组赛后截图')
    placeholders = ','.join('?' for _ in ids)
    rows = c.execute(f'SELECT * FROM postgame_images WHERE id IN ({placeholders})', tuple(ids)).fetchall()
    found = {str(row['id']): row for row in rows}
    missing = [image_id for image_id in ids if image_id not in found]
    if missing:
        raise HTTPException(400, f'部分截图还没有分页识别结果（{len(missing)} 张未识别）；'
                                 '请先完成截图分页识别，再重新选择')
    results = []
    for image_id in ids:
        row = found[image_id]
        result = json.loads(row['result'])
        result['imageId'] = row['id']
        result['imageName'] = None
        results.append(result)
    return results


def _channel_bodies(c):
    rows = c.execute('SELECT id, body FROM channels').fetchall()
    channels = []
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        if isinstance(channel, dict):
            channels.append(channel)
    return channels


def _channel_using_images(c, image_ids):
    """已把「全部」所选截图挂进 screenshot.imageIds 的通道。

    只拦「整组都已被同一条通道用过」的重复录入；部分重叠允许（新组可能复用
    个别截图），避免把替换重传误判成重复。
    """
    wanted = {str(value) for value in image_ids}
    if not wanted:
        return None
    for channel in _channel_bodies(c):
        used = {str(value) for value in
                ((channel.get('sources') or {}).get('screenshot') or {}).get('imageIds') or []}
        if wanted <= used:
            return channel
    return None


def _channel_using_recording(c, identities, recording_id):
    """通道里是否已经挂过这段录像。

    三线索：file.recordingId / file.sha256（视频）/ file.name（旧流程导出的
    报告 JSON 文件名）。旧数据只有文件名能和录像 meta 对上。
    """
    if not recording_id:
        return None
    for channel in _channel_bodies(c):
        for file in ((channel.get('sources') or {}).get('video') or {}).get('files') or []:
            if recording_store.match_file(file, identities) == recording_id:
                return channel
    return None


def _describe_channel(channel):
    """409 提示里带上对方是哪一局，方便教练直接找过去补采。"""
    match = channel.get('match') or {}
    labels = [str(match.get(key) or '').strip() for key in ('date', 'session', 'opponent')]
    label = ' · '.join(value for value in labels if value)
    if not label:
        label = '已有对局'
    return f'{label}（通道 {channel.get("id")}）'


def _screenshot_entry_match(value, group):
    """新建 OCR 通道时的比赛级字段：body 优先，其次截图「战绩」页。"""
    group_match = group.get('match') or {}
    date = str(value.get('date') or '').strip() or str(group_match.get('date') or '').strip()
    session = str(value.get('session') or '').strip()
    opponent = str(value.get('opponent') or '').strip()
    if not (date or session or opponent):
        raise HTTPException(400, '请至少填写比赛日期、对手或训练分组')
    own_side = str(value.get('ownSide') or '').strip().lower()
    if own_side not in ('left', 'right'):
        own_side = 'left'  # 王者营地赛后截图左列 = 我方
    winner = str(value.get('winner') or '').strip().lower()
    if winner not in ('left', 'right'):
        winner = channel_store.derive_winner(own_side, group_match.get('result'))
    score = group_match.get('score') or {}
    return {'date': date, 'session': session, 'opponent': opponent,
            'scores': {'left': score.get('left'), 'right': score.get('right')},
            'durationSec': group_match.get('durationSec'),
            'mode': group_match.get('mode') or '',
            'ownSide': own_side, 'winner': winner or ''}


def _recording_match_date(report):
    """录屏报告里的日期 → YYYY-MM-DD。

    回放列表只显示 MM-DD HH:MM（没有年份），按当前年份补全；1 月录到 12 月的
    局会把年份回退一年，避免出现未来的日期。
    """
    match = report.get('match') or {}
    field = match.get('date') or {}
    value = field.get('value') if isinstance(field, dict) else field
    text, month, day = '', None, None
    if isinstance(value, dict):
        text = str(value.get('text') or '').strip()
        month, day = value.get('month'), value.get('day')
    elif value:
        text = str(value).strip()
    full = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if full:
        return f'{int(full.group(1)):04d}-{int(full.group(2)):02d}-{int(full.group(3)):02d}'
    if not (month and day):
        partial = re.search(r'(\d{1,2})-(\d{1,2})', text)
        if partial:
            month, day = int(partial.group(1)), int(partial.group(2))
    try:
        month, day = int(month), int(day)
    except (TypeError, ValueError):
        return ''
    today = datetime.now()
    try:
        moment = datetime(today.year, month, day)
    except ValueError:
        return ''
    if (moment - today).days > 1:
        try:
            moment = datetime(today.year - 1, month, day)
        except ValueError:
            return ''
    return moment.strftime('%Y-%m-%d')


def _recording_mode(report):
    match = report.get('match') or {}
    field = match.get('mode') or {}
    value = field.get('value') if isinstance(field, dict) else field
    return str(value or '').strip()


def _recording_duration(report):
    try:
        number = float(report.get('replayDuration'))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0 < number <= 24 * 3600:
        return None
    return int(round(number))


def _recording_own_side(report):
    pov = report.get('pov') or {}
    camp = str(pov.get('camp') or '').strip().lower()
    return {'blue': 'left', 'red': 'right'}.get(camp, '')


def _recording_file_info(meta, recording_id):
    return {'name': str(meta.get('name') or '录屏.mp4'),
            'size': meta.get('size'),
            'sha256': str(meta.get('sha256') or ''),
            'recordingId': str(recording_id)}


@app.post('/api/channels/from-screenshots')
def channel_from_screenshots(value: dict):
    """用一整组七页赛后截图「新录入一局」（不挂靠已有营地通道）。"""
    raw_ids = value.get('imageIds')
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(400, '请选择同一局的七张赛后截图')
    image_ids = [str(item) for item in raw_ids]
    if len(set(image_ids)) != len(image_ids):
        raise HTTPException(400, '这批截图有重复，请重新选择')
    with db() as c:
        results = _postgame_results(c, image_ids)
        groups = merge_postgame_pages(results)
        if len(groups) != 1:
            raise HTTPException(400, f'所选截图不是同一局（识别结果分成 {len(groups)} 组）；'
                                     '请只选同一局的七页截图')
        group = groups[0]
        present = {page.get('pageType') for page in group.get('pages') or []}
        missing_pages = [PAGE_NAMES[page] for page in PAGE_TYPES if page not in present]
        if missing_pages:
            raise HTTPException(400, '七页齐全才能新建一局；缺：' + '、'.join(missing_pages))
        if len(group.get('players') or []) != 10:
            raise HTTPException(400, f'这组截图识别出 {len(group.get("players") or [])} 人，'
                                     '不是完整十人；请检查是否漏页或截图中断')
        used = _channel_using_images(c, image_ids)
        if used is not None:
            raise HTTPException(409, f'这些截图已经全部挂到 {_describe_channel(used)}，'
                                     '不能重复新建；如需补采请直接在该局继续上传。')
        match_info = _screenshot_entry_match(value, group)
        channel = channel_store.blank(match_info)
        channel['entry'] = {'mode': 'ocr', 'primary': 'screenshot'}
        channel['id'] = uuid.uuid4().hex
        channel['_createdAt'] = time.time()
        channel_store.append_log(channel, 'create', value.get('actor'),
                                 {'entry': 'ocr', 'primary': 'screenshot'})
        try:
            channel_store.attach_screenshot(channel, group, image_ids, value.get('actor'))
        except ValueError as error:
            raise HTTPException(400, str(error))
        _save_channel(c, channel)
        return channel


@app.post('/api/channels/from-recording')
def channel_from_recording(value: dict):
    """用一段已识别的录屏「新录入一局」（不挂靠已有营地通道）。"""
    recording_id = str(value.get('recordingId') or '').strip()
    if not recording_id:
        raise HTTPException(400, '请选择要新建对局的录屏')
    try:
        meta = recording_store.read_meta(recording_id)
    except recording_store.RecordingError as error:
        raise HTTPException(404, str(error))
    try:
        report = recording_store.read_report(recording_id)
    except recording_store.RecordingError:
        raise HTTPException(409, '这段录屏还没有识别报告：请先在「录屏识别」里完成识别，再新建对局')
    roster = [row for camp in ('blue', 'red')
              for row in ((report.get('lineups') or {}).get(camp) or [])
              if row.get('hero')]
    if len(roster) < 10:
        raise HTTPException(400, f'录像没有识别出完整十人阵容（当前 {len(roster)} 人）；'
                                 '请重新识别录屏，或改用七张赛后截图新建一局')
    date = str(value.get('date') or '').strip() or _recording_match_date(report)
    session = str(value.get('session') or '').strip()
    opponent = str(value.get('opponent') or '').strip()
    if not (date or session or opponent):
        raise HTTPException(400, '请至少填写比赛日期、对手或训练分组')
    own_side = str(value.get('ownSide') or '').strip().lower()
    if own_side not in ('left', 'right'):
        own_side = _recording_own_side(report)
    winner = str(value.get('winner') or '').strip().lower()
    if winner not in ('left', 'right'):
        winner = ''  # 录像没有终局胜负，只能由教练在 body 里指定
    with db() as c:
        known = recording_store.identities(recording_store.list_recordings())
        used = _channel_using_recording(c, known, recording_id)
        if used is not None:
            raise HTTPException(409, f'这段录屏已经补采到 {_describe_channel(used)}，'
                                     '不能重复新建；如需补采请直接在该局继续上传。')
        match_info = {'date': date, 'session': session, 'opponent': opponent,
                      'scores': {'left': None, 'right': None},
                      'mode': _recording_mode(report),
                      'durationSec': _recording_duration(report),
                      'ownSide': own_side, 'winner': winner}
        channel = channel_store.blank(match_info)
        channel['entry'] = {'mode': 'ocr', 'primary': 'video'}
        channel['id'] = uuid.uuid4().hex
        channel['_createdAt'] = time.time()
        channel_store.append_log(channel, 'create', value.get('actor'),
                                 {'entry': 'ocr', 'primary': 'video',
                                  'recordingId': recording_id})
        channel_store.attach_video(channel, _recording_file_info(meta, recording_id),
                                   report, value.get('actor'))
        _save_channel(c, channel)
        return channel


@app.post('/api/channels/{channel_id}/screenshot')
def channel_attach_screenshot(channel_id: str, value: dict):
    """补采截图：默认把已有 imageIds 与本次选择做并集后整体重新识别/合并。

    教练可以先传 3 页、再传剩下 4 页；body.replace=true 时只用本次选择替换
    （整组重传）。并集跨了两局时，如果「仅本次选择」能组成完整十人局，按
    替换处理；否则提示改用 replace=true。
    """
    raw_ids = value.get('imageIds')
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(400, '请选择同一组截图')
    incoming = [str(item) for item in raw_ids]
    if len(set(incoming)) != len(incoming):
        raise HTTPException(400, '本次选择的截图有重复，请重新选择')
    replace = bool(value.get('replace'))
    with db() as c:
        channel = _load_channel(c, channel_id)
        existing = [str(item) for item in
                    ((channel.get('sources') or {}).get('screenshot') or {}).get('imageIds') or []]
        # 本次选择排前面：postgame_ocr 合并同页型字段是「先到先得」，重拍/重传的
        # 新图必须盖过旧值，否则补采看起来成功、数据却没更新。
        ids = incoming if replace else list(dict.fromkeys(incoming + existing))
        results = _postgame_results(c, ids)
        groups = merge_postgame_pages(results)
        if len(groups) == 1 and len(groups[0].get('players') or []) == 10:
            group = groups[0]
        elif not replace:
            incoming_groups = merge_postgame_pages(_postgame_results(c, incoming))
            if len(incoming_groups) != 1:
                raise HTTPException(400, '本次选择的截图属于不同对局，请只选同一局')
            incoming_group = incoming_groups[0]
            incoming_pages = {page.get('pageType') for page in incoming_group.get('pages') or []}
            # 只有「本次选择本身也是完整七页十人组」才自动按替换处理，避免只补
            # 几页时把已挂的整组截图意外清掉。
            if len(incoming_group.get('players') or []) == 10 and len(incoming_pages) >= 7:
                ids, group = incoming, incoming_group
            elif len(groups) != 1:
                raise HTTPException(400, '已挂的截图和本次上传不是同一局；'
                                         '如确认整组替换请用 replace=true')
            else:
                raise HTTPException(400, f'合并后识别出 {len(groups[0].get("players") or [])} 人，'
                                         '不是完整十人；请检查是否漏页或截图中断；'
                                         '如确认整组替换请用 replace=true')
        else:
            if len(groups) != 1:
                raise HTTPException(400, f'本次选择的截图属于不同对局（{len(groups)} 组），'
                                         '请只选同一局')
            raise HTTPException(400, f'这批截图识别出 {len(groups[0].get("players") or [])} 人，'
                                     '不是完整十人；请检查是否漏页或截图中断')
        try:
            channel_store.attach_screenshot(channel, group, ids, value.get('actor'))
        except ValueError as error:
            raise HTTPException(400, str(error))
        _save_channel(c, channel, value.get('actor'))
        return channel


@app.post('/api/channels/{channel_id}/replay')
def channel_attach_replay(channel_id: str, value: dict):
    replay_id = value.get('replayId')
    if not replay_id:
        raise HTTPException(400, '请选择回放记录')
    with db() as c:
        channel = _load_channel(c, channel_id)
        try:
            _, report = _replay_body(c, replay_id)
        except ValueError as error:
            raise HTTPException(404, str(error))
        channel_store.attach_replay(channel, replay_id, report, value.get('actor'))
        _save_channel(c, channel, value.get('actor'))
        return channel


@app.post('/api/channels/{channel_id}/table')
async def channel_attach_table(channel_id: str, request: Request):
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > 64 * 1024 * 1024:
            raise HTTPException(413, '表格请小于 64 MB')
        chunks.append(chunk)
    data = b''.join(chunks)
    name = request.query_params.get('name', '数据表.xlsx')[:200]
    suffix = Path(name).suffix.lower()
    if suffix not in ('.csv', '.tsv', '.txt', '.xlsx', '.xlsm'):
        raise HTTPException(400, '仅支持 CSV/TSV/XLSX/XLSM')
    digest = hashlib.sha256(data).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix='kpl-channel-') as folder:
            path = Path(folder) / ('upload' + suffix)
            path.write_bytes(data)
            workbook = read_workbook(path)
            if not workbook.get('sheets'):
                raise ValueError('表格没有工作表')
            sheet = workbook['sheets'][0]
            with db() as validation_db:
                current_channel = _load_channel(validation_db, channel_id)
            existing_ids = {(row.get('keys') or {}).get('matchId') for row in ((current_channel.get('sources') or {}).get('table') or {}).get('rows') or []}
            validate_sheet(sheet, current_channel.get('match'), existing_ids - {None, ''})
            profile = infer_profile(sheet)
            parsed = apply_profile(sheet, profile)
            parsed['grain'] = profile.get('grain')
            parsed['profile'] = {key: profile.get(key) for key in ('grain', 'keys', 'metrics')}
    except Exception as error:
        raise HTTPException(400, f'表格解析失败：{error}')
    rows = parsed.get('rows') or []
    if len(rows) > 5000:
        parsed['warnings'] = list(parsed.get('warnings') or []) + ['只保留前 5000 行用于采集草稿合并。']
        parsed['rows'] = rows[:5000]
    with db() as c:
        channel = _load_channel(c, channel_id)
        channel_store.attach_table(channel, {'name': name, 'size': len(data), 'sha256': digest}, parsed, request.query_params.get('actor'))
        c.execute('INSERT OR IGNORE INTO channel_files(id,channel_id,kind,name,mime,data,uploaded_at) VALUES(?,?,?,?,?,?,?)',
                  (digest, channel_id, 'table', name, 'application/octet-stream', data, time.time()))
        _save_channel(c, channel, request.query_params.get('actor'))
        return channel


@app.post('/api/channels/{channel_id}/video')
async def channel_attach_video(channel_id: str, request: Request):
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > 16 * 1024 * 1024:
            raise HTTPException(413, '录像 OCR 报告请小于 16 MB')
        chunks.append(chunk)
    data = b''.join(chunks)
    name = request.query_params.get('name', '录像报告.json')[:200]
    digest = hashlib.sha256(data).hexdigest()
    try:
        report = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(400, f'录像报告不是有效 JSON：{error}')
    if not isinstance(report, dict) or not report.get('lineups'):
        raise HTTPException(400, '录像报告缺少 lineups，不是回放录屏 OCR 报告')
    with db() as c:
        channel = _load_channel(c, channel_id)
        channel_store.attach_video(channel, {'name': name, 'size': len(data), 'sha256': digest}, report,
                                   request.query_params.get('actor'))
        c.execute('INSERT OR IGNORE INTO channel_files(id,channel_id,kind,name,mime,data,uploaded_at) VALUES(?,?,?,?,?,?,?)',
                  (digest, channel_id, 'video', name, 'application/json', data, time.time()))
        _save_channel(c, channel, request.query_params.get('actor'))
        return channel


@app.patch('/api/channels/{channel_id}/draft')
def channel_edit_draft(channel_id: str, value: dict):
    try:
        with db() as c:
            channel = _load_channel(c, channel_id)
            channel_store.apply_draft(channel, value.get('players'), value.get('actor'))
            _save_channel(c, channel, value.get('actor'))
            return channel
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.post('/api/channels/{channel_id}/review')
def channel_review(channel_id: str, value: dict):
    try:
        with db() as c:
            channel = _load_channel(c, channel_id)
            channel_store.set_review(channel, value.get('reviewedBy'), value.get('notes'), value.get('actor'))
            _save_channel(c, channel)
            return channel
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.post('/api/channels/{channel_id}/save')
def channel_save(channel_id: str, value: dict | None = None):
    """写入正式统计。

    客户端对「无缺失值」的局直接调这里，不再要求先人工标记复核；
    有缺失值的局仍要已复核或显式 allowMissing，避免把缺字段的数据静默入库。
    """
    value = value or {}
    try:
        with db() as c:
            channel = _load_channel(c, channel_id)
            draft = channel.get('draft') or {}
            missing = draft.get('missing') or []
            reviewed = (channel.get('review') or {}).get('status') == 'reviewed'
            if missing and not reviewed and not bool(value.get('allowMissing')):
                labels = '、'.join(f'{item.get("label")}缺{item.get("missing")}/10'
                                   for item in missing)
                raise HTTPException(400, f'这局还有缺失值：{labels}；请逐条确认后再保存。')
            if not reviewed:
                # OCR 新录入没有营地自动同步，复核人默认写成「截图/录屏录入」，方便追溯。
                default_reviewer = ('截图/录屏录入' if channel_store.entry_mode(channel) == 'ocr'
                                    else AUTO_REVIEWER)
                reviewer = str(value.get('reviewedBy') or default_reviewer).strip() or default_reviewer
                channel_store.set_review(channel, reviewer, str(value.get('notes') or ''))
            data = _write_channel_bundle(channel)
            _save_channel(c, channel, value.get('actor') or value.get('reviewedBy'), 'save')
            return {'channel': channel, 'bundle': data}
    except HTTPException:
        raise
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error))


@app.post('/api/channels/approve')
def channels_approve(value: dict):
    """批量通过无缺失通道；带缺失值的通道必须逐个明确确认。

    - 不传 channelIds：只处理营地通道中无缺失值且尚未入库的局。
    - 传 channelIds + allowMissing：逐条确认缺失后通过（界面会先二次确认）。
    """
    raw_ids = value.get('channelIds')
    ids = {str(item) for item in raw_ids} if isinstance(raw_ids, list) else set()
    allow_missing = bool(value.get('allowMissing'))
    if allow_missing and not ids:
        raise HTTPException(400, '确认缺失必须指定具体对局，不能整批通过')
    reviewer = str(value.get('reviewedBy') or '本机一键通过').strip() or '本机一键通过'
    notes = str(value.get('notes') or '').strip()

    with db() as c:
        rows = c.execute('SELECT id, body FROM channels').fetchall()
    passed, skipped, failed = [], [], []
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        channel_id = str(channel.get('id') or row['id'])
        if ids and channel_id not in ids:
            continue
        official_id = str((channel.get('official') or {}).get('id') or '')
        if not ids and not official_id.startswith('camp-'):
            continue
        if (channel.get('saved') or {}).get('status') == 'saved':
            continue
        try:
            channel_store.rebuild(channel)
        except Exception as error:
            failed.append({'id': channel_id, 'error': str(error)})
            continue
        result = _approve_channel(channel, reviewer, notes, allow_missing=allow_missing)
        if not result.get('ok'):
            skipped.append({'id': channel_id, 'missing': result.get('missing') or [],
                            'error': result.get('error') or ''})
            continue
        try:
            with db() as c:
                _save_channel(c, channel, reviewer, 'approve')
            passed.append({'id': channel_id, 'bundleKey': result.get('bundleKey'),
                           'missing': result.get('missing') or []})
        except Exception as error:
            failed.append({'id': channel_id, 'error': str(error)})
    if passed:
        _invalidate_v3_snapshot()
    return {'ok': True, 'passed': passed, 'skipped': skipped, 'failed': failed}


@app.delete('/api/channels/{channel_id}')
def channel_delete(channel_id: str):
    with db() as c:
        row = c.execute('SELECT 1 FROM channels WHERE id=?', (channel_id,)).fetchone()
        if not row:
            raise HTTPException(404, '采集通道不存在')
        c.execute('DELETE FROM channel_files WHERE channel_id=?', (channel_id,))
        c.execute('DELETE FROM channels WHERE id=?', (channel_id,))
    return {'ok': True}


# ---- replay checkpoint state (offline state_table/state.jsonl) ----------------
# Gold/KDA/level are engine-measured only on rows carrying arena_stats; HP is a
# normalized engine sample. Trajectory x/z failed validation and is kept out of
# the product table. Nothing here interpolates missing state.
MAX_CHECKPOINT_ROWS = 200_000
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
CHECKPOINT_SCHEMA = 'kpl-replay-checkpoints-v1'
CHECKPOINT_NUMERIC_FIELDS = {
    'gold': (0, 10_000_000),
    'kills': (0, 1_000),
    'deaths': (0, 1_000),
    'assists': (0, 1_000),
    'level': (0, 100),
    'hp_current': (0, 1_000_000),
    'hp_max': (0, 1_000_000),
    'hp_ratio': (0, 10),
    'abs_hp_estimate': (0, 1_000_000),
    'hp_max_abs': (0, 1_000_000),
}
CHECKPOINT_CONFIDENCE = {
    'gold': 'engine_measured', 'kills': 'engine_measured', 'deaths': 'engine_measured',
    'assists': 'engine_measured', 'kda': 'engine_measured', 'level': 'engine_measured',
    'hp_current': 'measured', 'hp_max': 'measured', 'hp_ratio': 'measured',
    'abs_hp_estimate': 'unknown', 'hp_max_abs': 'unknown',
    'x': 'estimated', 'z': 'estimated', 'positions': 'estimated',
}
CHECKPOINT_CONFIDENCE_NOTE = ('金币/KDA/等级仅在 sources 含 arena_stats 的检查点行为引擎实测；'
                               'HP 为引擎归一化采样；事件行与插值帧不标为实测。')
CHECKPOINT_NOTES = [
    '金币/KDA/等级只在 sources 含 arena_stats 的检查点行按引擎实测展示；事件行保持 null，不推断。',
    'HP 为引擎归一化采样（hp_max 约 1000，不是绝对血量）；abs_hp_estimate 仅在可读到绝对上限时提供。',
    '位置 x/z 来自轨迹重建（验证 RMS 17.8% 地图跨度，未通过），不进入检查点表。',
    '插值帧未并入本表；独立 UI 误差上限约 1,012 金币 / 3.68 KDA（09:01），只作趋势参考。',
]


class CheckpointDataError(ValueError):
    """检查点状态不符合 schema。"""


class CheckpointPayloadTooLarge(CheckpointDataError):
    """检查点状态超过行数或字节上限。"""


def _checkpoint_number(value, name, low=None, high=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CheckpointDataError(f'{name} 必须是数字或 null')
    if isinstance(value, float) and not math.isfinite(value):
        raise CheckpointDataError(f'{name} 不是有限数字')
    if low is not None and value < low:
        raise CheckpointDataError(f'{name} 超出范围')
    if high is not None and value > high:
        raise CheckpointDataError(f'{name} 超出范围')
    return value


def _checkpoint_text(value, name, limit=200, required=False):
    if value is None:
        if required:
            raise CheckpointDataError(f'{name} 缺失')
        return None
    if not isinstance(value, str) or not value.strip():
        raise CheckpointDataError(f'{name} 必须是非空字符串')
    value = value.strip()
    if len(value) > limit:
        raise CheckpointDataError(f'{name} 过长')
    if any(ord(ch) < 32 for ch in value):
        raise CheckpointDataError(f'{name} 含控制字符')
    return value


def _checkpoint_row(value, where):
    if not isinstance(value, dict):
        raise CheckpointDataError(f'{where} 必须是 JSON 对象')
    row = dict(value)
    time_s = _checkpoint_number(row.get('time_s'), f'{where} time_s', 0, 1_000_000)
    if time_s is None:
        raise CheckpointDataError(f'{where} 缺少 time_s')
    row['time_s'] = time_s
    frame = _checkpoint_number(row.get('frame'), f'{where} frame', 0, 10_000_000)
    if frame is not None:
        if float(frame) != int(frame):
            raise CheckpointDataError(f'{where} frame 必须是整数')
        frame = int(frame)
    row['frame'] = frame
    row['player'] = _checkpoint_text(row.get('player'), f'{where} player', 80, required=True)
    row['hero'] = _checkpoint_text(row.get('hero'), f'{where} hero', 80)
    for field, (low, high) in CHECKPOINT_NUMERIC_FIELDS.items():
        row[field] = _checkpoint_number(row.get(field), f'{where} {field}', low, high)
    for field in ('entity_id', 'camp', 'unit', 'slot'):
        if field not in row:
            continue
        number = _checkpoint_number(row[field], f'{where} {field}', -1_000_000_000, 1_000_000_000)
        if number is not None:
            if float(number) != int(number):
                raise CheckpointDataError(f'{where} {field} 必须是整数')
            number = int(number)
        row[field] = number
    for field, limit in (('time_mmss', 32), ('row_kind', 40), ('pos_source', 40),
                         ('event_families', 400), ('time_origin', 40)):
        if field in row:
            row[field] = _checkpoint_text(row[field], f'{where} {field}', limit)
    if 'sources' in row:
        sources = row['sources']
        if isinstance(sources, list):
            if len(sources) > 32:
                raise CheckpointDataError(f'{where} sources 过多')
            sources = ';'.join(_checkpoint_text(item, f'{where} sources', 60, required=True)
                               for item in sources)
        else:
            sources = _checkpoint_text(sources, f'{where} sources', 2_000)
        row['sources'] = sources
    for field in ('note', 'notes'):
        if field not in row:
            continue
        note = row[field]
        if note is not None:
            if not isinstance(note, str):
                raise CheckpointDataError(f'{where} {field} 必须是字符串')
            note = note.strip()
            if len(note) > 4_000:
                raise CheckpointDataError(f'{where} {field} 过长')
            if '\x00' in note:
                raise CheckpointDataError(f'{where} {field} 含非法字符')
            note = note or None
        row[field] = note
    return row


def _checkpoint_payload_rows(data):
    """Parse a JSONL body or a JSON object/list into validated rows + metadata."""
    if not data:
        raise CheckpointDataError('检查点数据为空')
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise CheckpointPayloadTooLarge('检查点数据请小于 64 MB')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise CheckpointDataError('检查点数据不是 UTF-8') from error
    text = text.strip()
    if not text:
        raise CheckpointDataError('检查点数据为空')

    metadata = {}
    value = None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        raw_rows = value
    elif isinstance(value, dict):
        if isinstance(value.get('rows'), list):
            raw_rows = value['rows']
            for key in ('fileName', 'note', 'schema'):
                if value.get(key) is not None:
                    metadata[key] = value[key]
        else:
            raw_rows = [value]
    else:
        raw_rows = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if len(raw_rows) >= MAX_CHECKPOINT_ROWS:
                raise CheckpointPayloadTooLarge(
                    f'检查点行数超过上限（最多 {MAX_CHECKPOINT_ROWS:,} 行）')
            try:
                raw_rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise CheckpointDataError(f'第 {number} 行不是合法 JSON') from error

    if not raw_rows:
        raise CheckpointDataError('检查点数据没有行')
    if len(raw_rows) > MAX_CHECKPOINT_ROWS:
        raise CheckpointPayloadTooLarge(
            f'检查点行数超过上限（最多 {MAX_CHECKPOINT_ROWS:,} 行）')
    rows = [_checkpoint_row(item, f'第 {index + 1} 行') for index, item in enumerate(raw_rows)]
    if metadata.get('fileName') is not None:
        metadata['fileName'] = _checkpoint_text(metadata['fileName'], 'fileName', 200)
    return rows, metadata


def _checkpoint_counts(rows):
    def present(row, *fields):
        return all(row.get(field) is not None for field in fields)

    gold_rows = sum(1 for row in rows if row.get('gold') is not None)
    kda_rows = sum(1 for row in rows if present(row, 'kills', 'deaths', 'assists'))
    level_rows = sum(1 for row in rows if row.get('level') is not None)
    hp_rows = sum(1 for row in rows
                  if any(row.get(field) is not None
                         for field in ('hp_current', 'hp_max', 'hp_ratio')))
    state_rows = sum(1 for row in rows
                     if any(row.get(field) is not None
                            for field in ('gold', 'kills', 'deaths', 'assists', 'level',
                                          'hp_current', 'hp_max', 'hp_ratio',
                                          'abs_hp_estimate', 'hp_max_abs')))
    engine_rows = sum(1 for row in rows
                      if 'arena_stats' in str(row.get('sources') or '').split(';'))
    times = sorted({round(float(row['time_s']), 3) for row in rows
                    if row.get('gold') is not None
                    or any(row.get(field) is not None
                           for field in ('hp_current', 'hp_max', 'hp_ratio'))})
    return {
        'totalRows': len(rows),
        'stateRows': state_rows,
        'goldRows': gold_rows,
        'kdaRows': kda_rows,
        'levelRows': level_rows,
        'hpRows': hp_rows,
        'engineRows': engine_rows,
        'eventOnlyRows': len(rows) - state_rows,
        'checkpointTimes': times,
    }


def store_checkpoints(c, replay_id, data, file_name=None):
    rows, metadata = _checkpoint_payload_rows(data)
    name = _checkpoint_text(file_name, 'fileName', 200) if file_name else metadata.get('fileName')
    now = time.time()
    source = {
        'fileName': name,
        'sha256': hashlib.sha256(data).hexdigest(),
        'size': len(data),
        'rowCount': len(rows),
        'importedAt': now,
    }
    body = {
        'schema': CHECKPOINT_SCHEMA,
        'rows': rows,
        'source': source,
        'confidence': CHECKPOINT_CONFIDENCE,
        'confidenceNote': CHECKPOINT_CONFIDENCE_NOTE,
        'counts': _checkpoint_counts(rows),
        'notes': CHECKPOINT_NOTES,
    }
    c.execute('INSERT INTO replay_checkpoints VALUES(?,?,?) '
              'ON CONFLICT(replay_id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at',
              (replay_id, json.dumps(body, ensure_ascii=False, allow_nan=False), now))
    return {'replayId': replay_id, 'schema': CHECKPOINT_SCHEMA, 'imported': True,
            'rowCount': len(rows), 'source': source, 'confidence': CHECKPOINT_CONFIDENCE,
            'confidenceNote': CHECKPOINT_CONFIDENCE_NOTE, 'counts': body['counts']}


def _replay_exists(c, replay_id):
    return bool(c.execute('SELECT 1 FROM replays WHERE id=?', (replay_id,)).fetchone())


def store_replay(c, abc_id, ope_id=None):
    from replay_parser import inspect_replay
    if not isinstance(abc_id,str) or not re.fullmatch(r'[a-f0-9]{64}',abc_id):
        raise ValueError('请先上传 .abc 文件')
    if ope_id is not None and (not isinstance(ope_id,str) or not re.fullmatch(r'[a-f0-9]{64}',ope_id)):
        raise ValueError('.ope 文件标识无效')
    abc=c.execute('SELECT * FROM replay_files WHERE id=?',(abc_id,)).fetchone()
    ope=c.execute('SELECT * FROM replay_files WHERE id=?',(ope_id,)).fetchone() if ope_id else None
    if not abc or abc['kind'] != 'abc' or (ope_id and (not ope or ope['kind'] != 'ope')):
        raise ValueError('未找到对应类型的回放文件，请重新上传')
    old=c.execute('SELECT * FROM replays WHERE id=?',(abc_id,)).fetchone()
    old_report=json.loads(old['body']) if old else {}
    if old and old['ope_file_id'] and ope_id and old['ope_file_id'] != ope_id:
        raise ValueError('这份 .abc 已关联另一份 .ope，未覆盖已有配对')
    if old and (not ope_id or old['ope_file_id'] == ope_id):
        return old_report,False
    report=inspect_replay(bytes(abc['data']),bytes(ope['data']) if ope else None)
    now=time.time()
    report.update({'id':abc_id,'abcFileName':abc['name'],'opeFileName':ope['name'] if ope else None,
                   'createdAt':old['created_at'] if old else now,'updatedAt':now})
    if old_report.get('runtime'):
        report['runtime']=old_report['runtime']
    c.execute('INSERT INTO replays VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ope_file_id=excluded.ope_file_id,body=excluded.body,updated_at=excluded.updated_at',
              (abc_id,abc_id,ope_id,json.dumps(report,ensure_ascii=False),report['createdAt'],now))
    return report,True


def _replay_body(c, replay_id):
    row=c.execute('SELECT * FROM replays WHERE id=?',(replay_id,)).fetchone()
    if not row:
        raise ValueError('回放记录不存在')
    return row,json.loads(row['body'])


def attach_runtime_file(c, replay_id, file_id):
    if not isinstance(file_id,str) or not re.fullmatch(r'[a-f0-9]{64}',file_id):
        raise ValueError('运行时数据文件标识无效')
    _,report=_replay_body(c,replay_id)
    source=c.execute('SELECT * FROM replay_files WHERE id=? AND kind=?',(file_id,'runtime')).fetchone()
    if not source:
        raise ValueError('未找到运行时数据文件')
    data=bytes(source['data'])
    analysis=analyze_jsonl(data)
    previous=report.get('runtime') or {}
    runtime={'fileId':file_id,'fileName':source['name'],'size':len(data),'sha256':file_id,
             'receivedAt':previous.get('receivedAt') if previous.get('fileId')==file_id else time.time(),
             'analysis':analysis}
    report['runtime']=runtime
    c.execute('UPDATE replays SET body=?,updated_at=? WHERE id=?',
              (json.dumps(report,ensure_ascii=False,allow_nan=False),time.time(),replay_id))
    old_file=previous.get('fileId')
    if old_file and old_file != file_id:
        referenced=any((json.loads(row['body']).get('runtime') or {}).get('fileId')==old_file
                       for row in c.execute('SELECT body FROM replays WHERE id<>?',(replay_id,)))
        if not referenced:
            c.execute("DELETE FROM replay_files WHERE id=? AND kind='runtime'",(old_file,))
    return runtime


def store_runtime(c, replay_id, data):
    _replay_body(c,replay_id)
    file_id=hashlib.sha256(data).hexdigest()
    inserted=c.execute('INSERT OR IGNORE INTO replay_files VALUES(?,?,?,?)',
                       (file_id,f'runtime-{replay_id}.jsonl','runtime',data)).rowcount
    try:
        return attach_runtime_file(c,replay_id,file_id)
    except Exception:
        if inserted:
            c.execute("DELETE FROM replay_files WHERE id=? AND kind='runtime'",(file_id,))
        raise


@app.post('/api/replays/files')
async def upload_replay_file(request: Request):
    from replay_parser import MAX_FILE_BYTES,inspect_abc,parse_ope_bytes
    from starlette.concurrency import run_in_threadpool
    name=request.query_params.get('name','').replace('\\','/').rsplit('/',1)[-1][:200]
    kind=Path(name).suffix.lower().lstrip('.')
    if kind not in ('abc','ope'):
        raise HTTPException(400,'仅接收 .abc 与 .ope 回放文件')
    chunks=[];length=0
    async for chunk in request.stream():
        length+=len(chunk)
        if length > MAX_FILE_BYTES:
            raise HTTPException(413,'单个回放文件请小于 16 MB')
        chunks.append(chunk)
    data=b''.join(chunks)
    try:
        # Parsing is CPU-bound and takes ~0.3 s on a full match; keep it off the
        # event loop.  For .abc this also fills the parse cache that
        # /api/replays/import reuses, so one upload is decoded once.
        await run_in_threadpool(inspect_abc if kind == 'abc' else parse_ope_bytes, data)
    except ValueError as error:
        raise HTTPException(422,str(error))
    file_id=hashlib.sha256(data).hexdigest()
    with db() as c:
        c.execute('INSERT OR IGNORE INTO replay_files VALUES(?,?,?,?)',(file_id,name,kind,data))
    return {'id':file_id,'name':name,'kind':kind,'size':len(data)}


def _ensure_builds_async(abc_file_id: str, report: dict | None = None) -> None:
    """按局生成出装时间轴；失败只记日志，不影响导入结果。

    ``report`` 是导入时已经解析过的那份 .abc 结果，传下去就不用再解一遍。
    """
    def run() -> None:
        try:
            with db() as c:
                row = c.execute(
                    "SELECT name, data FROM replay_files WHERE id=?",
                    (abc_file_id,)).fetchone()
            if row is None:
                return
            digest = hashlib.sha256(row["data"]).hexdigest()
            if (BUILDS_DIR / digest / "meta.json").exists():
                return
            import replay_timeline_build
            replay_timeline_build.build_from_abc_bytes(
                row["data"], BUILDS_DIR, row["name"], None, report)
            print(f"[builds] built {digest[:12]} {row['name']}", flush=True)
        except Exception as error:  # 后台任务不能影响主流程
            print(f"[builds] build failed for {abc_file_id}: {error}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def _rebuild_builds_with_checkpoints(replay_id: str) -> None:
    """检查点补传后重建出装时间轴；Tier 2 在这里闭环。"""
    def run() -> None:
        try:
            with db() as c:
                replay = c.execute('SELECT abc_file_id FROM replays WHERE id=?',
                                   (replay_id,)).fetchone()
                if replay is None:
                    return
                abc = c.execute('SELECT name, data FROM replay_files WHERE id=?',
                                (replay['abc_file_id'],)).fetchone()
                row = c.execute('SELECT body FROM replay_checkpoints WHERE replay_id=?',
                                (replay_id,)).fetchone()
            if abc is None:
                return
            points = {}
            if row:
                body = json.loads(row['body'])
                for item in body.get('rows') or []:
                    if item.get('gold') is None and item.get('kills') is None:
                        continue
                    try:
                        second = int(float(item.get('time_s')))
                    except (TypeError, ValueError):
                        continue
                    key = str(item.get('entity_id') or '')
                    if key:
                        points.setdefault(second, {})[key] = item
            import replay_timeline_build
            meta = replay_timeline_build.build_from_abc_bytes(
                abc['data'], BUILDS_DIR, abc['name'], points or None)
            print(f"[builds] rebuilt {replay_id[:12]} tier={meta['tier']} "
                  f"checkpoint_seconds={len(points)}", flush=True)
        except Exception as error:
            print(f"[builds] rebuild failed for {replay_id}: {error}", flush=True)
    threading.Thread(target=run, daemon=True).start()


@app.post('/api/replays/import')
def import_replay(value: dict):
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            report,changed=store_replay(c,value.get('abcFileId'),value.get('opeFileId'))
    except ValueError as error:
        raise HTTPException(422,str(error))
    if value.get('abcFileId'):
        _ensure_builds_async(value['abcFileId'], report)
    return {'report':report,'changed':changed}


@app.get('/api/replays')
def replay_list():
    with db() as c:
        reports=[json.loads(r[0]) for r in c.execute('SELECT body FROM replays ORDER BY updated_at DESC')]
    return {'replays':reports}


@app.get('/api/replays/{replay_id}')
def replay_detail(replay_id: str):
    with db() as c:
        row=c.execute('SELECT body FROM replays WHERE id=?',(replay_id,)).fetchone()
    if not row:
        raise HTTPException(404,'回放记录不存在')
    return json.loads(row['body'])


@app.get('/api/replays/{replay_id}/report')
def replay_report(replay_id: str):
    return Response(json.dumps(replay_detail(replay_id),ensure_ascii=False,indent=2),media_type='application/json',
                    headers={'Content-Disposition':f'attachment; filename="replay-{replay_id}.json"'})


@app.get('/api/replays/{replay_id}/inputs')
def replay_inputs(replay_id: str, unit: int = None, stride: int = 1):
    """Decoded hero input timeline, computed on demand from the stored .abc."""
    from tools.replay_frame_commands import hero_inputs
    from tools.replay_input_timeline import build_unit_map
    with db() as c:
        row=c.execute('SELECT body FROM replays WHERE id=?',(replay_id,)).fetchone()
        if not row:
            raise HTTPException(404,'回放记录不存在')
        report=json.loads(row['body'])
        source=c.execute('SELECT data FROM replay_files WHERE id=? AND kind=?',(replay_id,'abc')).fetchone()
    if not source:
        raise HTTPException(404,'回放主体文件不存在')
    inputs=hero_inputs(bytes(source['data']))
    single_game=None
    if inputs['status']=='unsupported-route':
        from tools.replay_input_timeline import single_game_timeline
        single_game=single_game_timeline(bytes(source['data']))
    roster=build_unit_map(report.get('blocks') or [])
    heroes=[]
    for u,r in roster.items():
        ustats=(inputs['units'].get(str(u)) or {}).get('stats') or {}
        estats=(inputs['entities'].get(str(r.get('entityId'))) or {}).get('stats') or {}
        heroes.append({**r,'unit':u,
                       **{k:ustats.get(k) or 0 for k in ('moves','attacks','attacksWithObj')},
                       **{k:ustats.get(k) for k in ('firstFrame','lastFrame','dirMin','dirMax')},
                       **{k:estats.get(k) or 0 for k in ('buys','learnSkill','skills','cc')}})
    from tools.replay_frame_commands import FRAME_RATE
    import replay_time
    manual_buys=[row[0] for e in inputs['entities'].values() for row in e['buys'] if len(row)>3 and row[3] in (0,1)]
    last_manual=max(manual_buys) if manual_buys else None
    payload={'status':inputs['status'],'error':inputs.get('error'),
             'frameRecords':inputs['frameRecords'],'fullyParsedFrames':inputs['fullyParsedFrames'],
             'unresolvedFrames':inputs['unresolvedFrames'],'entryCounts':inputs['entryCounts'],
             'heroes':heroes,
             'timeBase':{'framesPerSecond':FRAME_RATE,
                         'battleStartFrame':list(replay_time.BATTLE_START_FRAME_APPROX),
                         'lastManualBuyFrame':last_manual,
                         'estimatedBattleSeconds':round(max(last_manual-7,0)/FRAME_RATE,1) if last_manual is not None else None,
                         'uncertaintySeconds':1,
                         'note':'t ≈ (frame − battleStart)/15；校准依据 既有校准（±1s）；帧率常量见 replay_time.py'},
             'provenance':{'moves':{'source':'abc-frame-commands','confidence':'decoded'},
                           'attacks':{'source':'abc-frame-commands','confidence':'decoded'},
                           'buys':{'source':'abc-frame-commands','confidence':'decoded'},
                           'positions':{'source':'abc-input-direction','confidence':'estimated'}},
             'confidence':{'moves':'decoded','attacks':'decoded','buys':'decoded',
                           'positions':'estimated'},
             'singleGame':single_game,
             'schema':'unit = 8 + (camp-1)*8 + 槽位；dir_deg 与方向技能瞄准同角度系（世界向量 = (cos d, sin d)，native +y 向南；罗盘 = (90+d)%360）'}
    if unit is not None:
        target=roster.get(unit)
        if not target:
            raise HTTPException(404,f'unit {unit} 不在十人槽位映射内')
        udata=inputs['units'].get(str(unit)) or {}
        edata=inputs['entities'].get(str(target.get('entityId'))) or {}
        from tools.replay_input_timeline import (annotate_buys, extract_wrapper_tlvs,
                                                 integrate_path, load_prices)
        prices=load_prices()
        wrapper=extract_wrapper_tlvs(bytes(source['data'])).get(str(target.get('entityId'))) or {}
        angles=wrapper.get('angle') or []
        anchors=[[e['frame'],e['x'],e['y']] for e in (report.get('playerEvents') or {}).get('positions',{}).get('events',[])
                 if e['entityId']==target.get('entityId') and e.get('kind')==2]
        def sample(rows,cap=4000):
            step=max(int(stride or 1),(len(rows)+cap-1)//cap if len(rows)>cap else 1)
            return rows[::step]
        payload['hero']={**target,'unit':unit,
                         'moves':sample(udata.get('moves') or []),
                         'attacks':sample(udata.get('attacks') or []),
                         'buys':annotate_buys(edata.get('buys') or [],prices),
                         'learnSkill':edata.get('learnSkill') or [],
                         'skills':edata.get('skills') or [],
                         'cc':edata.get('cc') or [],
                         'angleSamples':angles,
                         'pathEstimate':integrate_path(udata.get('moves') or []),
                         'pathNote':'方向积分形状估算：漂移严重（锚点残差 1.8万-6.5万），仅示意转向历史，绝非位置；既有校准',
                         'positionAnchors':anchors}
    return payload


_REPLAY_STATE_CACHE: dict = {}
_REPLAY_STATE_LOCK = threading.Lock()


@app.get('/api/replays/{replay_id}/state')
def replay_state(replay_id: str, rebuild: bool = False):
    """Per-second replay state decoded from the stored ``.abc``.

    Only the file-decode tier is produced here: roster, win/MVP/rating, the
    frame-precise purchase and skill-point ledgers, derived level and derived
    cumulative gold spent, plus per-second action counts.  Combat outcomes
    (kills, deaths, gold income, HP, continuous positions) are absent from the
    container and stay null with a reason in ``missing``; nothing is estimated.
    """
    from replay_state_engine import build_from_bytes
    with db() as c:
        row = c.execute('SELECT abc_file_id, ope_file_id FROM replays WHERE id=?',
                        (replay_id,)).fetchone()
        if not row:
            raise HTTPException(404, '回放记录不存在')
        abc = c.execute('SELECT data FROM replay_files WHERE id=? AND kind=?',
                        (row['abc_file_id'], 'abc')).fetchone()
        ope = c.execute('SELECT data FROM replay_files WHERE id=? AND kind=?',
                        (row['ope_file_id'], 'ope')).fetchone() if row['ope_file_id'] else None
    if not abc:
        raise HTTPException(404, '回放主体文件不存在')
    abc_bytes = bytes(abc['data'])
    ope_bytes = bytes(ope['data']) if ope else None
    key = (replay_id, hashlib.sha256(abc_bytes).hexdigest(),
           hashlib.sha256(ope_bytes).hexdigest() if ope_bytes else None)
    if not rebuild:
        with _REPLAY_STATE_LOCK:
            cached = _REPLAY_STATE_CACHE.get(key)
        if cached is not None:
            return cached
    document = build_from_bytes(abc_bytes, ope_bytes)
    with _REPLAY_STATE_LOCK:
        _REPLAY_STATE_CACHE[key] = document
        while len(_REPLAY_STATE_CACHE) > 6:
            _REPLAY_STATE_CACHE.pop(next(iter(_REPLAY_STATE_CACHE)))
    return document


@app.get('/api/replays/{replay_id}/skill-ledger')
def replay_skill_ledger(replay_id: str, unit: int = None, stride: int = 1):
    """Per-cast skill ledger decoded on demand from the stored .abc.

    Source tier is file-decode: cast attempts from the input stream, never hits.
    Engine-measured outcomes (paused-frame client-memory reads) are a separate
    optional tier: when attached they appear per cast under ``engine`` and in
    ``provenance.engine``; without them every ``engine`` stays null and the
    endpoint behaviour is unchanged.
    """
    from tools.replay_skill_ledger import engine_outcomes_summary, skill_ledger
    with db() as c:
        row=c.execute('SELECT body FROM replays WHERE id=?',(replay_id,)).fetchone()
        if not row:
            raise HTTPException(404,'回放记录不存在')
        source=c.execute('SELECT data FROM replay_files WHERE id=? AND kind=?',(replay_id,'abc')).fetchone()
    if not source:
        raise HTTPException(404,'回放主体文件不存在')
    ledger=skill_ledger(bytes(source['data']))
    engine_provenance=engine_outcomes_summary(ledger)
    if unit is not None:
        hero=next((item for item in ledger.get('heroes') or [] if item['unit']==unit),None)
        if hero is None:
            raise HTTPException(404,f'unit {unit} 不在十人槽位映射内')
        casts=[cast for cast in ledger['casts'] if cast['unit']==unit]
        cap=4000
        step=max(int(stride or 1),(len(casts)+cap-1)//cap if len(casts)>cap else 1)
        ledger={'status':ledger['status'],'tier':ledger['tier'],
                'frameRecords':ledger['frameRecords'],
                'unresolvedFrames':ledger['unresolvedFrames'],
                'timeBase':ledger['timeBase'],'hero':hero,
                'castsTotal':len(casts),'strideApplied':step,
                'casts':casts[::step],'limitations':ledger['limitations']}
    ledger=dict(ledger,provenance={
        'casts':{'source':'abc-frame-commands','tier':'file-decode','confidence':'decoded'},
        'targets':{'source':'abc-learnskill-object-pool','tier':'file-decode','confidence':'decoded'},
        'engine':engine_provenance,
        'notes':ledger.get('limitations') or []})
    return ledger


@app.post('/api/replays/{replay_id}/checkpoints')
async def upload_replay_checkpoints(replay_id: str, request: Request):
    """Import engine checkpoint rows (state.jsonl) without touching the report."""
    with db() as c:
        if not _replay_exists(c, replay_id):
            raise HTTPException(404, '回放记录不存在')
    chunks = []
    length = 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > MAX_CHECKPOINT_BYTES:
            raise HTTPException(413, '检查点数据请小于 64 MB')
        chunks.append(chunk)
    data = b''.join(chunks)
    name = (request.query_params.get('name') or '').replace('\\', '/').rsplit('/', 1)[-1][:200] or None
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not _replay_exists(c, replay_id):
                raise HTTPException(404, '回放记录不存在')
            summary = store_checkpoints(c, replay_id, data, name)
    except CheckpointPayloadTooLarge as error:
        raise HTTPException(413, str(error))
    except CheckpointDataError as error:
        raise HTTPException(422, str(error))
    _rebuild_builds_with_checkpoints(replay_id)
    return summary


@app.get('/api/replays/{replay_id}/checkpoints')
def replay_checkpoints(replay_id: str):
    with db() as c:
        if not _replay_exists(c, replay_id):
            raise HTTPException(404, '回放记录不存在')
        row = c.execute('SELECT body FROM replay_checkpoints WHERE replay_id=?',
                        (replay_id,)).fetchone()
    if not row:
        raise HTTPException(404, '尚未导入检查点状态')
    body = json.loads(row['body'])
    return {'replayId': replay_id, 'imported': True,
            'schema': body.get('schema', CHECKPOINT_SCHEMA),
            'rows': body.get('rows') or [],
            'source': body.get('source') or {},
            'confidence': body.get('confidence') or CHECKPOINT_CONFIDENCE,
            'confidenceNote': body.get('confidenceNote') or CHECKPOINT_CONFIDENCE_NOTE,
            'counts': body.get('counts') or _checkpoint_counts(body.get('rows') or []),
            'notes': body.get('notes') or CHECKPOINT_NOTES}


@app.delete('/api/replays/{replay_id}/checkpoints')
def delete_replay_checkpoints(replay_id: str):
    with db() as c:
        if not _replay_exists(c, replay_id):
            raise HTTPException(404, '回放记录不存在')
        deleted = c.execute('DELETE FROM replay_checkpoints WHERE replay_id=?',
                            (replay_id,)).rowcount
    if not deleted:
        raise HTTPException(404, '尚未导入检查点状态')
    return {'ok': True, 'replayId': replay_id}


@app.post('/api/replays/{replay_id}/runtime')
async def upload_runtime(replay_id: str, request: Request):
    chunks=[];length=0
    async for chunk in request.stream():
        length+=len(chunk)
        if length > MAX_RUNTIME_BYTES:
            raise HTTPException(413,'运行时数据请小于 8 MB')
        chunks.append(chunk)
    data=b''.join(chunks)
    if not data:
        raise HTTPException(422,'运行时数据为空')
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            runtime=store_runtime(c,replay_id,data)
    except RuntimeDataError as error:
        raise HTTPException(422,str(error))
    except ValueError as error:
        raise HTTPException(404,str(error))
    return runtime


@app.get('/api/replays/{replay_id}/runtime')
def replay_runtime(replay_id: str):
    try:
        with db() as c:
            _,report=_replay_body(c,replay_id)
    except ValueError as error:
        raise HTTPException(404,str(error))
    runtime=report.get('runtime')
    if not runtime:
        raise HTTPException(404,'尚未导入运行时数据')
    return runtime


@app.get('/api/replays/{replay_id}/runtime/file')
def replay_runtime_file(replay_id: str):
    try:
        with db() as c:
            _,report=_replay_body(c,replay_id)
            runtime=report.get('runtime') or {}
            source=c.execute('SELECT * FROM replay_files WHERE id=? AND kind=?',(runtime.get('fileId'),'runtime')).fetchone()
    except ValueError as error:
        raise HTTPException(404,str(error))
    if not source:
        raise HTTPException(404,'运行时数据文件不存在')
    return Response(bytes(source['data']),media_type='application/x-ndjson',
                    headers={'Content-Disposition':f'attachment; filename="runtime-{replay_id}.jsonl"'})


@app.get('/api/backup')
def backup():
    with db() as c:
        value = {'schema': 1, 'settings': settings(c), 'matches': records(c),
                 'images': [{'id': r['id'], 'name': r['name'], 'mime': r['mime'], 'data': base64.b64encode(r['data']).decode(), 'ocr': r['ocr']} for r in c.execute('SELECT * FROM images')],
                 'postgameImages': [{'id': r['id'], 'result': json.loads(r['result']), 'updatedAt': r['updated_at']}
                                    for r in c.execute('SELECT * FROM postgame_images')],
                 'channels': [{'id': r['id'], 'revision': r['revision'], 'body': json.loads(r['body']),
                               'createdAt': r['created_at'], 'updatedAt': r['updated_at']}
                              for r in c.execute('SELECT * FROM channels')],
                 'channelFiles': [{'id': r['id'], 'channelId': r['channel_id'], 'kind': r['kind'],
                                   'name': r['name'], 'mime': r['mime'],
                                   'data': base64.b64encode(r['data']).decode(), 'uploadedAt': r['uploaded_at']}
                                  for r in c.execute('SELECT * FROM channel_files')],
                 'revisions': [dict(r) for r in c.execute('SELECT * FROM revisions')],
                 'focusItems': [{'id': r['id'], 'body': json.loads(r['body']),
                                 'createdAt': r['created_at'], 'updatedAt': r['updated_at']}
                                for r in c.execute('SELECT * FROM focus_items')],
                 'replayFiles':[{'id':r['id'],'name':r['name'],'kind':r['kind'],'data':base64.b64encode(r['data']).decode()} for r in c.execute('SELECT * FROM replay_files')],
                 'replays':[{'abcFileId':r['abc_file_id'],'opeFileId':r['ope_file_id'],
                             'runtimeFileId':(json.loads(r['body']).get('runtime') or {}).get('fileId')} for r in c.execute('SELECT * FROM replays')]}
    return Response(json.dumps(value, ensure_ascii=False), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="training-backup.json"'})


@app.post('/api/restore')
def restore(value: dict):
    try:
        if value.get('schema') != 1:
            raise ValueError('不支持的备份版本')
        imported_settings = validate_settings(value['settings'])
        imported = [validate_match(m, imported_settings['roster']) for m in value['matches']]
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            current = settings(c)
            ids = {p['id'] for p in current['roster']}
            merged = dict(current)
            merged['roster'] = current['roster'] + [p for p in imported_settings['roster'] if p['id'] not in ids]
            if not ids:
                merged['teamName'] = imported_settings['teamName']
            validate_settings(merged)
            for im in value.get('images', []):
                data = base64.b64decode(im['data'], validate=True)
                if len(data) > MAX_IMAGE or hashlib.sha256(data).hexdigest() != im['id']:
                    raise ValueError('备份图片校验失败')
                with Image.open(io.BytesIO(data)) as source:
                    if im['mime'] != {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(source.format):
                        raise ValueError('备份图片类型错误')
                    source.verify()
                if im.get('ocr') is not None:
                    parsed = json.loads(im['ocr'])
                    if not isinstance(parsed, dict) or not isinstance(parsed.get('scores', {}), dict):
                        raise ValueError('备份识别记录格式错误')
                c.execute('INSERT OR IGNORE INTO images VALUES(?,?,?,?,?)', (im['id'], im['name'], im['mime'], data, im.get('ocr')))
            for item in value.get('postgameImages', []):
                if not isinstance(item, dict) or not isinstance(item.get('result'), dict):
                    raise ValueError('备份分页截图记录格式错误')
                image_id = item.get('id')
                if not isinstance(image_id, str) or not c.execute('SELECT 1 FROM images WHERE id=?', (image_id,)).fetchone():
                    raise ValueError('备份分页截图缺少对应图片')
                if not isinstance(item['result'].get('players', []), list):
                    raise ValueError('备份分页截图结果格式错误')
                c.execute('INSERT OR IGNORE INTO postgame_images(id,result,updated_at) VALUES(?,?,?)',
                          (image_id, json.dumps(item['result'], ensure_ascii=False),
                           float(item.get('updatedAt') or time.time())))
            for item in value.get('channels', []):
                if not isinstance(item, dict) or not isinstance(item.get('body'), dict):
                    raise ValueError('备份采集通道格式错误')
                channel_id = item.get('id')
                if not isinstance(channel_id, str) or channel_id != item['body'].get('id'):
                    raise ValueError('备份采集通道 ID 不匹配')
                c.execute('INSERT OR IGNORE INTO channels(id,revision,body,created_at,updated_at) VALUES(?,?,?,?,?)',
                          (channel_id, int(item.get('revision') or 1),
                           json.dumps(item['body'], ensure_ascii=False),
                           float(item.get('createdAt') or time.time()),
                           float(item.get('updatedAt') or time.time())))
            for item in value.get('channelFiles', []):
                data = base64.b64decode(item.get('data', ''), validate=True)
                if not isinstance(item.get('id'), str) or hashlib.sha256(data).hexdigest() != item['id']:
                    raise ValueError('备份采集文件校验失败')
                if not c.execute('SELECT 1 FROM channels WHERE id=?', (item.get('channelId'),)).fetchone():
                    raise ValueError('备份采集文件缺少通道')
                c.execute('INSERT OR IGNORE INTO channel_files(id,channel_id,kind,name,mime,data,uploaded_at) VALUES(?,?,?,?,?,?,?)',
                          (item['id'], item['channelId'], item.get('kind') or 'file',
                           str(item.get('name') or 'file')[:200], item.get('mime') or 'application/octet-stream',
                           data, float(item.get('uploadedAt') or time.time())))
            for item in value.get('focusItems', []):
                if not isinstance(item, dict) or not isinstance(item.get('body'), dict):
                    raise ValueError('备份训练重点格式错误')
                body = focus_module.validate_item(item['body'], {p['id'] for p in merged['roster']})
                c.execute('INSERT OR IGNORE INTO focus_items(id,body,created_at,updated_at) VALUES(?,?,?,?)',
                          (item.get('id'), json.dumps(body, ensure_ascii=False),
                           float(item.get('createdAt') or time.time()),
                           float(item.get('updatedAt') or time.time())))
            added, skipped = 0, 0
            existing_images = set()
            for old in records(c):
                if old['status'] == 'confirmed':
                    existing_images.update(old.get('imageIds', []))
            for m in imported:
                if not isinstance(m.get('id'), str) or not m['id']:
                    raise ValueError('备份比赛 ID 缺失')
                for image_id in m.get('imageIds', []):
                    if not c.execute('SELECT 1 FROM images WHERE id=?', (image_id,)).fetchone():
                        raise ValueError('备份缺少关联图片')
                if c.execute('SELECT 1 FROM matches WHERE id=?', (m['id'],)).fetchone():
                    skipped += 1
                    continue
                if m['status'] == 'confirmed' and existing_images & set(m.get('imageIds', [])):
                    raise ValueError('备份含重复截图比赛，已取消整次恢复')
                if m['status'] == 'confirmed':
                    check_evidence(c, m.get('imageIds', []), m.get('evidenceReviews'))
                    existing_images.update(m.get('imageIds', []))
                validate_icon_reviews(c, m)
                m['revision'] = 1
                body = json.dumps(m, ensure_ascii=False, allow_nan=False)
                c.execute('INSERT INTO matches VALUES(?,?,?)', (m['id'], 1, body))
                c.execute('INSERT INTO revisions(match_id,saved_at,body) VALUES(?,?,?)', (m['id'], time.time(), body))
                added += 1
            for revision in value.get('revisions', []):
                previous = json.loads(revision['body'])
                if previous.get('id') != revision['match_id']:
                    raise ValueError('备份修订记录的比赛 ID 不匹配')
                validate_match(previous, imported_settings['roster'])
                if not c.execute('SELECT 1 FROM matches WHERE id=?', (revision['match_id'],)).fetchone():
                    raise ValueError('备份修订记录缺少对应比赛')
                if not c.execute('SELECT 1 FROM revisions WHERE match_id=? AND body=?', (revision['match_id'], revision['body'])).fetchone():
                    c.execute('INSERT INTO revisions(match_id,saved_at,body) VALUES(?,?,?)', (revision['match_id'], revision['saved_at'], revision['body']))
            from replay_parser import MAX_FILE_BYTES,inspect_replay,parse_ope_bytes
            for file in value.get('replayFiles',[]):
                data=base64.b64decode(file['data'],validate=True)
                if len(data)>MAX_FILE_BYTES or hashlib.sha256(data).hexdigest()!=file['id']:
                    raise ValueError('备份回放文件校验失败')
                if file['kind']=='abc':
                    inspect_replay(data)
                elif file['kind']=='ope':
                    parse_ope_bytes(data)
                elif file['kind']=='runtime':
                    if len(data)>MAX_RUNTIME_BYTES:
                        raise ValueError('备份运行时数据过大')
                    analyze_jsonl(data)
                else:
                    raise ValueError('备份回放类型无效')
                c.execute('INSERT OR IGNORE INTO replay_files VALUES(?,?,?,?)',(file['id'],file['name'][:200],file['kind'],data))
            replay_added=0
            for replay in value.get('replays',[]):
                _,changed=store_replay(c,replay.get('abcFileId'),replay.get('opeFileId'))
                replay_added+=bool(changed)
                runtime_file_id=replay.get('runtimeFileId')
                if runtime_file_id:
                    attach_runtime_file(c,replay.get('abcFileId'),runtime_file_id)
            c.execute('UPDATE settings SET body=? WHERE id=1', (json.dumps(merged, ensure_ascii=False),))
    except (ValueError, TypeError, KeyError, OSError) as e:
        raise HTTPException(400, f'备份恢复失败：{e}')
    result={'added': added, 'skipped': skipped}
    if value.get('replays'):
        result['replaysAddedOrUpdated']=replay_added
    return result


@app.get('/analysis')
def analysis_index():
    # V3 已是默认界面，旧别名直接回根路径。
    return RedirectResponse('/', status_code=302)


@app.get('/v3')
@app.get('/v3/{path:path}')
def v3_legacy(path: str = ''):
    # 旧版 /v3 下的链接（包括静态资源）统一回根路径。
    return RedirectResponse('/' + path, status_code=302)


app.state.source_backup = backup
app.state.source_restore = restore


@app.get('/studio')
def studio_index():
    # 旧版入口统一回 V3。
    return RedirectResponse('/', status_code=302)


_V3_INDEX_FALLBACK = """<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <meta name="description" content="面向教练的赛训数据平台">
  <title>赛训数据</title>
  <link rel="stylesheet" href="static/style.css">
  <link rel="stylesheet" href="static/workspace-home.css">
  <script type="module" src="static/app.js"></script>
</head>
<body>
  <a class="skip" href="#content">跳至内容</a>
  <div id="app"></div>
</body>
</html>
"""


def _v3_asset_stamp() -> str:
    """V3 外壳引用 app.js / style.css 的 ``?v=`` 值。

    以前只用 index.html 自己的 mtime：index.html 从 1.5.x 起就没再变过，
    所以 1.6.0–1.6.4 每个版本生成的 URL 完全一样（``app.js?v=1794271492``）。
    覆盖安装后只要浏览器、标签页或中间层还留着这个 URL 的旧响应，看起来就是
    「某些页面还是旧页面」，普通刷新也救不回来。改成版本号 + public 下最新
    文件 mtime：每次发版、每次改前端文件都会换 URL，旧缓存自然失效。
    """
    newest = 0
    public = ROOT / 'v3' / 'public'
    try:
        for item in public.rglob('*'):
            if item.is_file() and '__pycache__' not in item.parts:
                newest = max(newest, int(item.stat().st_mtime))
    except OSError:
        newest = 0
    return f'{VERSION}-{newest}'


def _v3_index_body() -> str:
    """读 V3 外壳并做三件事：

    1. 外壳被外部编辑器写坏（编码错乱 / 引号丢失）时回退到内置版本——
       否则浏览器会把后面的 link/script 吞掉，整页空白且没有任何报错。
    2. 资源版本按版本号 + public 最新 mtime 注入，index.html 本身不必再手改 ?v=。
    3. 注入 ``<meta name="app-version">``：页面据此判断自己是不是旧版本，
       服务端已经换成新版本时提示教练刷新（见 update-banner.js）。
    """
    path = ROOT / 'v3' / 'public' / 'index.html'
    try:
        text = path.read_bytes().decode('utf-8-sig')
    except (OSError, UnicodeDecodeError):
        text = ''
    broken = ('<script' not in text) or ('id="app"' not in text)
    if not broken:
        for tag in re.findall(r'<(?:meta|link|script)\b[^>]*>', text):
            if tag.count('"') % 2:
                broken = True
                break
    if broken:
        text = _V3_INDEX_FALLBACK
    stamp = _v3_asset_stamp()
    # godmode.js 也要吃同一个戳：它以前把 ?v=8.0.0 写死在 index.html 里，
    # 升级后 URL 不变，浏览器会一直用旧副本，改了也看不到。
    text = re.sub(r'(static/(?:style\.css|workspace-home\.css|app\.js|godmode\.js))(\?v=[^"\']*)?',
                  lambda match: f'{match.group(1)}?v={stamp}', text)
    if 'name="app-version"' not in text:
        text = re.sub(r'<head>',
                      f'<head>\n  <meta name="app-version" content="{VERSION}">',
                      text, count=1)
    return text


@app.get('/')
def index():
    # 根路径直接返回 V3 界面。
    # /v3 与 /studio 只是旧链接兼容。
    v3_index = ROOT / 'v3' / 'public' / 'index.html'
    if v3_index.is_file():
        return Response(_v3_index_body(), media_type='text/html; charset=utf-8')
    return JSONResponse({'detail': 'V3 前端资源缺失，请重新安装完整包'}, status_code=503)


# 2026-11-07：旧的 /legacy 独立外壳（web/index.html + style.css）已归档到
# .archive/2026-11-07-frontend-cleanup/，此路由随之删除。它没有任何入站链接。


@app.get('/api/health')
def health():
    return {'ok': True, 'pid': os.getpid(), 'dbPath': str(DB_PATH),
            'matchesDir': str(MATCHES_DIR), 'importsDir': str(IMPORTS_DIR),
            'version': VERSION, 'releaseDate': RELEASE_DATE, 'releaseName': RELEASE_NAME}


@app.post('/api/shutdown')
def shutdown(request: Request):
    """Graceful stop used by the launcher and the installer.

    Loopback only: a remote client must never be able to kill the workbench,
    even when ``TRAINING_ALLOW_REMOTE=1`` is set for LAN access.
    """
    client = request.client.host if request.client else ''
    if client not in ('127.0.0.1', '::1', '::ffff:127.0.0.1'):
        raise HTTPException(403, '只允许本机停止服务')

    def exit_later() -> None:
        time.sleep(0.4)
        os._exit(0)

    threading.Thread(target=exit_later, name='kpl-shutdown', daemon=True).start()
    return {'ok': True, 'stopping': True, 'pid': os.getpid()}


app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')
app.mount('/catalog', StaticFiles(directory=ROOT / 'resources', check_dir=False), name='catalog')


# ---------------------------------------------------------------------------
# V3：单应用入口
#
# 历史上分析接口曾独立成第二个服务；现在全部并进同一个 app。
# 现在 V3（v3/serve.py）的路由已改成 APIRouter，并进同一个 app：
#   /          V3 默认界面
#   /static    V3 前端资源
#   /api/*     采集/校对接口 + 分析接口（同一张路由表）
#   /v3       旧链接 302 到根路径
# 采集接口注册在前，路径重复时优先命中；分析接口的 /api/matches 是 GET，
# 采集侧的同名路由是 POST，不会互相遮挡。
# ---------------------------------------------------------------------------
def _mount_v3() -> bool:
    global V3_MODULE
    path = ROOT / 'v3' / 'serve.py'
    if not path.is_file():
        print('[v3] 未找到 v3/serve.py，跳过加载')
        return False
    try:
        # serve.py 依赖同目录的 deep_analysis.py，加载前把它所在的目录加进搜索路径
        v3_dir = str(path.parent)
        if v3_dir not in sys.path:
            sys.path.insert(0, v3_dir)
        spec = importlib.util.spec_from_file_location('kpl_v3_app', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules['kpl_v3_app'] = module
        spec.loader.exec_module(module)
        V3_MODULE = module
        app.include_router(module.router)
        app.mount('/static', StaticFiles(directory=path.parent / 'public'), name='v3-static')
        print('[v3] 已加载路由与 /static')
        return True
    except Exception as exc:                       # noqa: BLE001
        print(f'[v3] 加载失败，根路径会提示前端资源缺失: {exc}')
        return False


_mount_v3()


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.environ.get('TRAINING_HOST', '127.0.0.1'),
                port=int(os.environ.get('TRAINING_PORT', '8766')))
