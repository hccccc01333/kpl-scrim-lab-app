"""Loopback-only training review app; SQLite holds records and original images."""
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from domain import summarize, validate_match
from ocr import recognize
from vision import OCR_VERSION, catalog, crop_box, descriptor, prepare_image

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('TRAINING_DB', ROOT / 'data' / 'training.sqlite3'))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_IMAGE = 12 * 1024 * 1024


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
        CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, match_id TEXT, saved_at REAL, body TEXT);
        ''')
        c.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps({'teamName': '我的训练队', 'roster': []}, ensure_ascii=False),))


init_db()
app = FastAPI(title='训练赛分析工作台', docs_url=None, redoc_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    if host not in ('127.0.0.1', 'localhost', '[::1]'):
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method != 'GET' and origin and origin not in (f'http://{request.headers.get("host")}',):
        return JSONResponse({'detail': '来源不匹配，请从本地工作台操作'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
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
        images = [dict(r) for r in c.execute('SELECT id,name,mime,ocr IS NOT NULL AS recognized FROM images')]
    return {'settings': s, 'matches': matches, 'images': images, 'summary': summarize(matches, s['roster'])}


@app.put('/api/settings')
def save_settings(value: dict):
    try:
        value = validate_settings(value)
        with db() as c:
            old = settings(c)
            if not {p['id'] for p in old['roster']}.issubset({p['id'] for p in value['roster']}):
                raise ValueError('已有队员请保留，避免历史记录失去身份关联')
            c.execute('UPDATE settings SET body=? WHERE id=1', (json.dumps(value, ensure_ascii=False),))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True}


@app.get('/api/summary')
def summary(request: Request):
    q = request.query_params
    with db() as c:
        matches = records(c)
        roster = settings(c)['roster']
    filtered = [m for m in matches
                if (not q.get('from') or m.get('date', '') >= q['from'])
                and (not q.get('to') or m.get('date', '') <= q['to'])
                and q.get('opponent', '').strip().lower() in m.get('opponent', '').lower()
                and q.get('version', '').strip().lower() in m.get('version', '').lower()
                and (not q.get('player') or any(p.get('playerId') == q['player'] and p['side'] == m.get('side') for p in m['players']))]
    result = summarize(filtered, roster)
    # For a selected player, hero statistics describe that player's hero use.
    if q.get('player'):
        from copy import deepcopy
        personal = deepcopy(filtered)
        for m in personal:
            m['players'] = [p for p in m['players'] if p.get('playerId') == q['player'] and p['side'] == m.get('side')]
        player_result = summarize(personal, roster)
        result['heroes'], result['players'] = player_result['heroes'], player_result['players']
    return result


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


@app.get('/api/backup')
def backup():
    with db() as c:
        value = {'schema': 1, 'settings': settings(c), 'matches': records(c),
                 'images': [{'id': r['id'], 'name': r['name'], 'mime': r['mime'], 'data': base64.b64encode(r['data']).decode(), 'ocr': r['ocr']} for r in c.execute('SELECT * FROM images')],
                 'revisions': [dict(r) for r in c.execute('SELECT * FROM revisions')]}
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
            c.execute('UPDATE settings SET body=? WHERE id=1', (json.dumps(merged, ensure_ascii=False),))
    except (ValueError, TypeError, KeyError, OSError) as e:
        raise HTTPException(400, f'备份恢复失败：{e}')
    return {'added': added, 'skipped': skipped}


@app.get('/')
def index():
    return FileResponse(ROOT / 'web' / 'index.html')


app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')
app.mount('/catalog', StaticFiles(directory=ROOT / 'resources', check_dir=False), name='catalog')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('TRAINING_PORT', '8766')))
