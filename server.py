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
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from analysis_api import create_analysis_router
from match_review import create_review_router
from studio_api import create_studio_router
from replay_v2_api import create_v2_router
import focus as focus_module
import camp_replay
from collection_contract import validate_sheet
import channel_store
import mimo_ocr
import ocr_jobs
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
DB_PATH = Path(os.environ.get('TRAINING_DB', ROOT / 'data' / 'training.sqlite3'))
MATCHES_DIR = Path(os.environ.get('ANALYSIS_MATCHES', ROOT / 'data' / 'matches'))
IMPORTS_DIR = Path(os.environ.get('ANALYSIS_IMPORTS', ROOT / 'data' / 'imports'))
OFFICIAL_DIR = Path(os.environ.get('ANALYSIS_OFFICIAL', ROOT / 'data' / 'official_replays'))
V2_DIR = Path(os.environ.get('ANALYSIS_V2', ROOT / 'data' / 'v2'))
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
        ''')
        c.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps({'teamName': '我的训练队', 'roster': []}, ensure_ascii=False),))


init_db()
app = FastAPI(title='训练赛分析工作台', docs_url=None, redoc_url=None)
app.include_router(create_analysis_router(DB_PATH, MATCHES_DIR, IMPORTS_DIR))
app.include_router(create_studio_router(DB_PATH, MATCHES_DIR, IMPORTS_DIR))
app.include_router(create_v2_router(V2_DIR))
app.include_router(create_review_router(MATCHES_DIR, OFFICIAL_DIR, V2_DIR, ROOT))


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0].strip('[]').lower()
    if not _ALLOW_REMOTE and host not in _ALLOWED_HOSTS:
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method != 'GET' and origin and origin not in (f'http://{request.headers.get("host")}',):
        return JSONResponse({'detail': '来源不匹配，请从本地工作台操作'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/assets') or request.url.path in ('/', '/analysis'):
        # 本机工作台经常直接替换 web/ 下的文件；每次协商校验，避免浏览器用旧样式
        response.headers['Cache-Control'] = 'no-cache'
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
            raise ValueError('请填写有效队员昵称')
        ids.add(p['id'])
        if p.get('position', '') not in ['', '对抗路', '打野', '中路', '发育路', '游走']:
            raise ValueError('队员默认分路无效')
    aliases = value.get('aliases', {})
    if not isinstance(aliases, dict) or len(aliases) > 2000:
        raise ValueError('昵称别名映射无效')
    for label, player_id in aliases.items():
        if (not isinstance(label, str) or not label.strip() or len(label) > 80
                or player_id not in ids):
            raise ValueError('昵称别名映射包含无效队员或昵称')
    value['aliases'] = aliases
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
            if isinstance(value, dict) and 'aliases' not in value:
                value['aliases'] = old.get('aliases', {})
            value = validate_settings(value)
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
    folder = ROOT / 'data' / 'screenshots' / 'samples'
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
        'ffmpeg': shutil.which('ffmpeg') is not None,
        'ffprobe': shutil.which('ffprobe') is not None,
        'storage': {'dbPath': str(DB_PATH), 'dbFreeBytes': db_free,
                    'recordingsFreeBytes': recording_store.free_bytes()},
        'jobs': ocr_jobs.list_jobs(limit=12),
        'recordings': recording_store.library_stats(),
    }


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
        try:
            result = camp_replay.import_link(url, force=bool(value.get('force')))
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
            })
        except camp_replay.CampReplayError as error:
            entry.update({'ok': False, 'error': str(error)})
        except Exception as error:  # 网络/磁盘等意外，同样不让整批失败
            entry.update({'ok': False, 'error': f'{type(error).__name__}: {error}'})
        items.append(entry)
    imported = sum(1 for item in items if item['ok'])
    return {'schema': 'camp-replay-batch-v1', 'total': len(items),
            'imported': imported, 'failed': len(items) - imported, 'items': items}


@app.get('/api/official/replays')
def list_official_replays():
    return {'schema': 'camp-replay-v1', 'replays': camp_replay.list_replays()}


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

CAMP_CONFIG_PATH = Path(os.environ.get('CAMP_CONFIG_FILE', ROOT / 'data' / 'camp_config.json'))
_camp_sync_lock = threading.Lock()
_camp_sync_job = {'running': False, 'result': None, 'error': None,
                  'startedAt': None, 'finishedAt': None}


def _camp_tools():
    tools = ROOT / 'tools'
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))


def _clean_camp_players(players) -> list:
    cleaned = []
    for player in players if isinstance(players, list) else []:
        if not isinstance(player, dict):
            continue
        camp_id = str(player.get('campUserId') or '').strip()
        if not camp_id.isdigit():
            continue
        cleaned.append({'nickname': str(player.get('nickname') or '').strip()[:40],
                        'campUserId': camp_id})
    return cleaned


def _camp_config_read() -> dict:
    try:
        value = json.loads(CAMP_CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'players': []}
    return {'players': _clean_camp_players(value.get('players'))}


def _camp_sync_worker(players):
    _camp_tools()
    import camp_sync
    results = []
    for player in players:
        try:
            summary = camp_sync.sync(player['campUserId'])
            results.append({'nickname': player['nickname'], 'campUserId': player['campUserId'],
                            'ok': True, 'summary': summary})
        except BaseException as error:  # camp_sync 用 SystemExit 报致命错误
            results.append({'nickname': player['nickname'], 'campUserId': player['campUserId'],
                            'ok': False, 'error': f'{type(error).__name__}: {error}'})
    return results


@app.get('/api/camp/auth')
def camp_auth_status():
    _camp_tools()
    import camp_auth
    return camp_auth.read_account()


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
    return camp_auth.poll_login_once(taskId)


@app.post('/api/camp/auth/clear')
def camp_auth_clear():
    _camp_tools()
    import camp_auth
    camp_auth.AUTH_PATH.unlink(missing_ok=True)
    return {'ok': True}


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
    details = list(camp_sync.DETAIL_DIR.glob('*.json')) if camp_sync.DETAIL_DIR.is_dir() else []
    return {**_camp_sync_job, 'detailsCount': len(details),
            'config': _camp_config_read(), 'auth': camp_auth.read_account()}


@app.post('/api/camp/sync')
def camp_sync_start():
    with _camp_sync_lock:
        if _camp_sync_job['running']:
            raise HTTPException(409, '同步已在进行中')
        players = _camp_config_read()['players']
        if not players:
            raise HTTPException(400, '请先在选手清单里添加至少一个营地 ID')
        _camp_sync_job.update({'running': True, 'result': None, 'error': None,
                               'startedAt': time.time(), 'finishedAt': None})

    def worker():
        try:
            results = _camp_sync_worker(players)
            _camp_sync_job.update({'running': False,
                                   'result': {'players': results}, 'finishedAt': time.time()})
        except Exception as error:
            _camp_sync_job.update({'running': False,
                                   'error': f'{type(error).__name__}: {error}',
                                   'finishedAt': time.time()})

    threading.Thread(target=worker, daemon=True).start()
    return {'ok': True}


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


def _channel_summary(channel):
    return {
        'id': channel.get('id'), 'revision': channel.get('revision'),
        'match': channel.get('match') or {}, 'sourceStatus': channel_store.source_status(channel),
        'coverage': (channel.get('draft') or {}).get('coverage') or {},
        'missing': (channel.get('draft') or {}).get('missing') or [],
        'review': channel.get('review') or {}, 'saved': channel.get('saved') or {},
        'updatedAt': channel.get('updatedAt'), 'changeLog': channel.get('changeLog') or [],
    }


@app.get('/api/channels')
def channels_list():
    with db() as c:
        rows = c.execute('SELECT * FROM channels ORDER BY updated_at DESC').fetchall()
    result = []
    for row in rows:
        try:
            channel = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        channel['revision'] = row['revision']
        result.append(_channel_summary(channel))
    return {'schema': channel_store.SCHEMA, 'channels': result}


@app.post('/api/channels')
def channel_create(value: dict):
    match = value.get('match') if isinstance(value.get('match'), dict) else value
    if not any(str(match.get(key) or '').strip() for key in ('date', 'opponent', 'session')):
        raise HTTPException(400, '请至少填写比赛日期、对手或训练分组')
    channel = channel_store.blank(match)
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


@app.post('/api/channels/{channel_id}/screenshot')
def channel_attach_screenshot(channel_id: str, value: dict):
    image_ids = value.get('imageIds')
    if not isinstance(image_ids, list) or not image_ids:
        raise HTTPException(400, '请选择同一组截图')
    with db() as c:
        channel = _load_channel(c, channel_id)
        placeholders = ','.join('?' for _ in image_ids)
        rows = c.execute(f'SELECT * FROM postgame_images WHERE id IN ({placeholders})', tuple(image_ids)).fetchall()
        if len(rows) != len(set(image_ids)):
            raise HTTPException(400, '部分截图还没有分页识别结果')
        results = []
        for row in rows:
            result = json.loads(row['result'])
            result['imageId'] = row['id']
            result['imageName'] = None
            results.append(result)
        groups = merge_postgame_pages(results)
        if len(groups) != 1:
            raise HTTPException(400, '所选截图属于不同比赛组，请只选同一局')
        group = groups[0]
        if len(group.get('players') or []) != 10:
            raise HTTPException(400, '该截图组不足 10 人')
        channel_store.attach_screenshot(channel, group, image_ids, value.get('actor'))
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
    name = request.query_params.get('name', '赛训表.xlsx')[:200]
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
def channel_save(channel_id: str):
    try:
        with db() as c:
            channel = _load_channel(c, channel_id)
            data = channel_store.bundle(channel)
            folder = MATCHES_DIR
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'channel-{channel_id}.json'
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            channel['saved'] = {'status': 'saved', 'bundleKey': data['match']['key'],
                                'savedAt': channel_store.now()}
            _save_channel(c, channel, None, 'save')
            return {'channel': channel, 'bundle': data}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error))


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
    from replay_parser import MAX_FILE_BYTES,inspect_replay,parse_ope_bytes
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
        inspect_replay(data) if kind == 'abc' else parse_ope_bytes(data)
    except ValueError as error:
        raise HTTPException(422,str(error))
    file_id=hashlib.sha256(data).hexdigest()
    with db() as c:
        c.execute('INSERT OR IGNORE INTO replay_files VALUES(?,?,?,?)',(file_id,name,kind,data))
    return {'id':file_id,'name':name,'kind':kind,'size':len(data)}


def _ensure_v2_async(abc_file_id: str) -> None:
    """按局生成 V2 时间轴；失败只记日志，不影响导入结果。"""
    def run() -> None:
        try:
            with db() as c:
                row = c.execute(
                    "SELECT name, data FROM replay_files WHERE id=?",
                    (abc_file_id,)).fetchone()
            if row is None:
                return
            digest = hashlib.sha256(row["data"]).hexdigest()
            if (V2_DIR / digest / "meta.json").exists():
                return
            import replay_v2_build
            replay_v2_build.build_from_abc_bytes(row["data"], V2_DIR, row["name"])
            print(f"[v2] built {digest[:12]} {row['name']}", flush=True)
        except Exception as error:  # 后台任务不能影响主流程
            print(f"[v2] build failed for {abc_file_id}: {error}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def _rebuild_v2_with_checkpoints(replay_id: str) -> None:
    """检查点补传后重建 V2 时间轴；Tier 2 在这里闭环。"""
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
            import replay_v2_build
            meta = replay_v2_build.build_from_abc_bytes(
                abc['data'], V2_DIR, abc['name'], points or None)
            print(f"[v2] rebuilt {replay_id[:12]} tier={meta['tier']} "
                  f"checkpoint_seconds={len(points)}", flush=True)
        except Exception as error:
            print(f"[v2] rebuild failed for {replay_id}: {error}", flush=True)
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
        _ensure_v2_async(value['abcFileId'])
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
    manual_buys=[row[0] for e in inputs['entities'].values() for row in e['buys'] if len(row)>3 and row[3] in (0,1)]
    last_manual=max(manual_buys) if manual_buys else None
    payload={'status':inputs['status'],'error':inputs.get('error'),
             'frameRecords':inputs['frameRecords'],'fullyParsedFrames':inputs['fullyParsedFrames'],
             'unresolvedFrames':inputs['unresolvedFrames'],'entryCounts':inputs['entryCounts'],
             'heroes':heroes,
             'timeBase':{'framesPerSecond':FRAME_RATE,'battleStartFrame':[0,14],
                         'lastManualBuyFrame':last_manual,
                         'estimatedBattleSeconds':round(max(last_manual-7,0)/FRAME_RATE,1) if last_manual is not None else None,
                         'uncertaintySeconds':1,
                         'note':'t ≈ (frame − battleStart)/15；校准依据 docs 5.129（±1s）'},
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
                         'pathNote':'方向积分形状估算：漂移严重（锚点残差 1.8万-6.5万），仅示意转向历史，绝非位置；docs 5.132',
                         'positionAnchors':anchors}
    return payload


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
    _rebuild_v2_with_checkpoints(replay_id)
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
    return RedirectResponse('/studio', status_code=302)


app.state.source_backup = backup
app.state.source_restore = restore


@app.get('/studio')
def studio_index():
    return FileResponse(ROOT / 'web' / 'studio.html')


@app.get('/')
def index():
    return FileResponse(ROOT / 'web' / 'studio.html')


@app.get('/legacy')
def legacy_index():
    return FileResponse(ROOT / 'web' / 'index.html')


@app.get('/api/health')
def health():
    return {'ok': True, 'pid': os.getpid(), 'dbPath': str(DB_PATH),
            'matchesDir': str(MATCHES_DIR), 'importsDir': str(IMPORTS_DIR)}


app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')
app.mount('/catalog', StaticFiles(directory=ROOT / 'resources', check_dir=False), name='catalog')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.environ.get('TRAINING_HOST', '127.0.0.1'),
                port=int(os.environ.get('TRAINING_PORT', '8766')))
