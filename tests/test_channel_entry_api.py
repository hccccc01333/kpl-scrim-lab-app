"""截图/录屏「新录入一局」通道 API 的验收测试。

覆盖场景（对应任务契约）：
a) 七页十人截图 → 新建 OCR 通道 → 审核/保存进正式统计；
b) 缺页 400 点名缺哪页、整组重复建档 409；
c) 录屏报告 → 新建 OCR 通道 → 复核后 allowMissing 保存；
d) 截图补采并集（3 页 + 4 页）、重复 attach 幂等、replace 替换；
e) 空营地通道仍要求「王者营地」链接，普通 POST /api/channels 行为不变；
另断言通道列表 summary 的 entry / screenshotImageIds / recordingShas。
"""
import hashlib
import io
import json
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import channel_store
import recording_store
import server
from collection_contract import PAGE_NAMES, PAGE_TYPES

OUT = Path(__file__).resolve().parents[1] / 'test-results'
OUT.mkdir(exist_ok=True)

LEFT_HEROES = ['虞姬', '夏侯惇', '妲己', '阿古朵', '钟馗']
RIGHT_HEROES = ['后羿', '关羽', '兰陵王', '张良', '公孙离']
# 七页截图识别出的扩展指标（与 postgame_ocr 字段同名）。
SCREENSHOT_EXTENDED = {'cs': 120, 'jungleGold': 6800, 'control': 27, 'healing': 8700,
                       'towerDamage': 117, 'damageConversion': 1.3,
                       'takenPerDeath': 26792.5}


def field(value):
    return {'value': value, 'raw': str(value), 'confidence': .9, 'box': None}


def postgame_result(page_type, *, date='2026-08-15', score=None, result='win', duration=1132,
                    kills=2):
    """一页完整十人的赛后截图识别结果（字段齐全，可直接入库）。"""
    score = dict(score or {'left': 14, 'right': 26})
    players = []
    for side, heroes in (('left', LEFT_HEROES), ('right', RIGHT_HEROES)):
        for slot, hero in enumerate(heroes):
            nickname = f'{side}{slot}'
            players.append({
                'side': side, 'slot': slot,
                'nickname': {'value': nickname, 'raw': nickname, 'confidence': .9},
                'hero': {'value': hero, 'raw': hero, 'confidence': .9},
                'heroStatus': 'exact', 'heroCandidates': [], 'heroReadings': [],
                'rating': field(8.0), 'title': None, 'mvp': False,
                'fields': {'kills': field(kills), 'deaths': field(3), 'assists': field(4),
                           'gold': field(9000), 'damageDealt': field(50000),
                           'damageTaken': field(30000), 'participation': field(50),
                           'cs': field(SCREENSHOT_EXTENDED['cs']),
                           'jungleGold': field(SCREENSHOT_EXTENDED['jungleGold']),
                           'control': field(SCREENSHOT_EXTENDED['control']),
                           'healing': field(SCREENSHOT_EXTENDED['healing']),
                           'towerDamage': field(SCREENSHOT_EXTENDED['towerDamage']),
                           'damageConversion': field(SCREENSHOT_EXTENDED['damageConversion']),
                           'takenPerDeath': field(SCREENSHOT_EXTENDED['takenPerDeath'])},
                'shares': {}, 'sources': ['data'],
            })
    return {'schema': 'kpl-postgame-screenshot-v1', 'version': 'postgame-tabbed-v3',
            'layout': 'postgame-tabbed-v3', 'file': f'{page_type}.png',
            'pageType': page_type, 'tab': page_type,
            'match': {'date': date, 'time': '21:30', 'durationSec': duration,
                      'mode': '王者峡谷—5v5', 'result': result, 'score': score},
            'players': players, 'coverage': {}, 'warnings': []}


def recording_report(*, pov='red', full_lineup=True):
    def rows(heroes, prefix):
        return [{'slot': slot, 'camp': 'blue' if prefix == '蓝' else 'red',
                 'hero': hero, 'nickname': f'{prefix}{slot}', 'heroStatus': 'exact'}
                for slot, hero in enumerate(heroes)]

    lineups = {'blue': rows(LEFT_HEROES, '蓝'), 'red': rows(RIGHT_HEROES, '红')}
    if not full_lineup:
        lineups['red'] = []
    return {'schema': 'kpl-replay-video-ocr-v1',
            'match': {'date': {'raw': '08-15 21:30',
                               'value': {'month': 8, 'day': 15, 'hour': 21,
                                         'minute': 30, 'text': '08-15 21:30'}},
                      'mode': {'raw': '王者峡谷—5v5', 'value': '王者峡谷—5v5'}},
            'pov': {'camp': pov},
            'lineups': lineups,
            'replayDuration': 1123.0,
            'coverage': {'lineupHeroes': 10}}


class ChannelEntryApiTests(unittest.TestCase):
    def setUp(self):
        self.old_db = server.DB_PATH
        self.old_matches = server.MATCHES_DIR
        self.old_library = recording_store.LIBRARY
        self.old_temp = recording_store.TEMP
        server.DB_PATH = OUT / f'channel-entry-{uuid.uuid4().hex}.sqlite3'
        server.MATCHES_DIR = OUT / f'channel-entry-matches-{uuid.uuid4().hex}'
        recording_store.LIBRARY = OUT / f'channel-entry-recordings-{uuid.uuid4().hex}'
        recording_store.TEMP = recording_store.LIBRARY / '.tmp'
        server.init_db()
        self.client = TestClient(server.app, base_url='http://localhost')
        assert self.client.put('/api/settings', json={
            'teamName': '录入测试队', 'roster': []}).status_code == 200
        self.image_counter = 0

    def tearDown(self):
        server.DB_PATH = self.old_db
        server.MATCHES_DIR = self.old_matches
        recording_store.LIBRARY = self.old_library
        recording_store.TEMP = self.old_temp

    # ---- helpers -----------------------------------------------------------
    def upload_image(self):
        stream = io.BytesIO()
        self.image_counter += 1
        Image.new('RGB', (320, 200), (10, 20, self.image_counter % 255)).save(stream, format='PNG')
        response = self.client.post('/api/images?name=shot.png', content=stream.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def add_pages(self, page_types, **extra):
        image_ids = []
        for page_type in page_types:
            image_id = self.upload_image()
            result = postgame_result(page_type, **extra)
            with server.db() as db:
                db.execute('INSERT INTO postgame_images(id,result,updated_at) VALUES(?,?,?)',
                           (image_id, json.dumps(result, ensure_ascii=False), 0))
            image_ids.append(image_id)
        return image_ids

    def create_channel(self, match=None):
        match = match or {'date': '2026-08-15', 'opponent': '测试对手', 'session': '录入验收'}
        response = self.client.post('/api/channels', json={'match': match})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def write_recording(self, report=None, *, sha='ab' * 32, with_report=True,
                        name='8月15日训练赛录屏.mp4'):
        recording_id = sha[:32]
        folder = recording_store.LIBRARY / recording_id
        folder.mkdir(parents=True, exist_ok=True)
        meta = {'id': recording_id, 'name': name, 'size': 123456,
                'sha256': sha, 'createdAt': 0, 'updatedAt': 0,
                'video': {'duration': 1123, 'width': 1600, 'height': 900},
                'status': 'done', 'report': {'available': True}}
        (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        if with_report:
            body = recording_report() if report is None else report
            (folder / 'report.json').write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
        return recording_id, sha

    def summary(self, channel_id):
        listing = self.client.get('/api/channels').json()['channels']
        return next(item for item in listing if item['id'] == channel_id)

    # ---- a) 七页截图新录入 → 审核 → 正式统计 -------------------------------
    def test_from_screenshots_creates_ocr_channel_and_saves(self):
        image_ids = self.add_pages(PAGE_TYPES, result='win')
        response = self.client.post('/api/channels/from-screenshots', json={
            'imageIds': image_ids, 'session': '8月训练赛', 'opponent': '测试对手'})
        self.assertIn(response.status_code, (200, 201), response.text)
        channel = response.json()
        self.assertEqual(channel['entry'], {'mode': 'ocr', 'primary': 'screenshot'})
        self.assertEqual(channel['sourceStatus']['mode'], 'ocr')
        self.assertTrue(channel['sourceStatus']['complete'])
        self.assertEqual(channel['sourceStatus']['requiredSources'], [])
        self.assertTrue(all(value == 0 for value in channel['sourceStatus']['required'].values()))
        self.assertEqual(channel['match']['date'], '2026-08-15')
        self.assertEqual(channel['match']['session'], '8月训练赛')
        self.assertEqual(channel['match']['opponent'], '测试对手')
        self.assertEqual(channel['match']['scores'], {'left': 14, 'right': 26})
        self.assertEqual(channel['match']['ownSide'], 'left')
        self.assertEqual(channel['match']['winner'], 'left')
        self.assertEqual(channel['match']['gametime'], '08-15 21:30')
        self.assertEqual(channel['match']['gameresult'], 1)
        self.assertEqual(len(channel['draft']['players']), 10)
        self.assertEqual(channel['review']['status'], 'unreviewed')

        summary = self.summary(channel['id'])
        self.assertEqual(summary['entry']['mode'], 'ocr')
        self.assertEqual(summary['screenshotImageIds'], image_ids)
        self.assertEqual(summary['recordingShas'], [])
        self.assertEqual(summary['recordingIds'], [])

        review = self.client.post(f"/api/channels/{channel['id']}/review",
                                  json={'reviewedBy': '教练甲', 'notes': '七页截图逐页核对'})
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()['review']['status'], 'reviewed')
        save = self.client.post(f"/api/channels/{channel['id']}/save")
        self.assertEqual(save.status_code, 200, save.text)
        bundle = save.json()['bundle']
        self.assertEqual(bundle['schema'], 'kpl-match-data-v1')
        self.assertEqual(len(bundle['players']), 10)
        path = server.MATCHES_DIR / f"channel-{channel['id']}.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(data['players']), 10)
        self.assertEqual(data['match']['ownSide'], 'left')
        self.assertEqual(data['match']['winner'], 'blue')

    def test_save_uses_ocr_default_reviewer(self):
        image_ids = self.add_pages(PAGE_TYPES)
        channel = self.client.post('/api/channels/from-screenshots', json={
            'imageIds': image_ids, 'session': '默认复核人'}).json()
        save = self.client.post(f"/api/channels/{channel['id']}/save")
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['channel']['review']['reviewedBy'], '截图/录屏录入')

    def test_from_screenshots_extended_fields_and_manual_override(self):
        """七页截图的扩展指标进草稿/正式数据包；校对页手工改后以 manual 为准。"""
        image_ids = self.add_pages(PAGE_TYPES)
        created = self.client.post('/api/channels/from-screenshots',
                                   json={'imageIds': image_ids, 'session': '扩展字段验收'})
        self.assertEqual(created.status_code, 200, created.text)
        channel_id = created.json()['id']

        detail = self.client.get(f'/api/channels/{channel_id}').json()
        draft = detail['draft']
        first = draft['players'][0]
        for key, value in SCREENSHOT_EXTENDED.items():
            self.assertEqual(first['fields'][key]['value'], value, key)
            self.assertEqual(first['fields'][key]['source'], 'screenshot', key)
        for key in SCREENSHOT_EXTENDED:
            self.assertEqual(draft['coverage'][key], 10, key)
        # 扩展字段缺失不挡审核：missing 仍只列 hero + 核心必填。
        self.assertFalse(any(item['field'] in SCREENSHOT_EXTENDED
                             for item in draft['missing']))

        review = self.client.post(f"/api/channels/{channel_id}/review",
                                  json={'reviewedBy': '教练甲'})
        self.assertEqual(review.status_code, 200, review.text)
        save = self.client.post(f"/api/channels/{channel_id}/save")
        self.assertEqual(save.status_code, 200, save.text)
        final = save.json()['bundle']['players'][0]['final']
        for key, value in SCREENSHOT_EXTENDED.items():
            self.assertEqual(final[key], value, key)

        # 校对页手工改 cs：PATCH draft 立即生效，重新复核保存后 bundle 取 manual 值。
        patch = self.client.patch(f'/api/channels/{channel_id}/draft', json={
            'players': [{'side': 'left', 'slot': 0, 'fields': {'cs': '99'}}]})
        self.assertEqual(patch.status_code, 200, patch.text)
        manual = patch.json()['draft']['players'][0]['fields']['cs']
        self.assertEqual(manual['value'], 99)
        self.assertEqual(manual['source'], 'manual')
        review2 = self.client.post(f"/api/channels/{channel_id}/review",
                                   json={'reviewedBy': '教练甲'})
        self.assertEqual(review2.status_code, 200, review2.text)
        save2 = self.client.post(f"/api/channels/{channel_id}/save")
        self.assertEqual(save2.status_code, 200, save2.text)
        saved = json.loads((server.MATCHES_DIR / f'channel-{channel_id}.json')
                           .read_text(encoding='utf-8'))
        self.assertEqual(saved['players'][0]['final']['cs'], 99)
        self.assertEqual(saved['players'][0]['final']['jungleGold'], 6800)

    # ---- b) 缺页 400 点名缺页 + 整组重复建档 409 ---------------------------
    def test_from_screenshots_requires_seven_pages_and_rejects_full_reuse(self):
        six = self.add_pages([page for page in PAGE_TYPES if page != 'team'], result='loss')
        response = self.client.post('/api/channels/from-screenshots',
                                    json={'imageIds': six, 'session': '缺页'})
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn('七页齐全', detail)
        self.assertIn(PAGE_NAMES['team'], detail)

        seven = six + self.add_pages(['team'], result='loss')
        payload = {'imageIds': seven, 'date': '2026-08-15',
                   'session': '补考', 'opponent': '对手B'}
        first = self.client.post('/api/channels/from-screenshots', json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['match']['winner'], 'right')  # result=loss + 默认左列

        again = self.client.post('/api/channels/from-screenshots', json=payload)
        self.assertEqual(again.status_code, 409)
        detail = again.json()['detail']
        self.assertIn('补考', detail)
        self.assertIn('2026-08-15', detail)

        # 只复用 1 张旧图的新一组（其余 6 张全新）允许创建：部分重叠不算重复。
        reused = seven[-1]
        new_pages = [page for page in PAGE_TYPES if page != 'team']
        mixed = [reused] + self.add_pages(new_pages, result='win')
        allowed = self.client.post('/api/channels/from-screenshots',
                                   json={'imageIds': mixed, 'session': '部分复用'})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertNotEqual(allowed.json()['id'], first.json()['id'])

    # ---- c) 录屏新录入 + allowMissing 保存 --------------------------------
    def test_from_recording_creates_ocr_channel_and_saves_with_missing(self):
        recording_id, sha = self.write_recording()
        response = self.client.post('/api/channels/from-recording', json={
            'recordingId': recording_id, 'session': '录像补录', 'opponent': '对手C'})
        self.assertEqual(response.status_code, 200, response.text)
        channel = response.json()
        self.assertEqual(channel['entry'], {'mode': 'ocr', 'primary': 'video'})
        self.assertEqual(channel['sourceStatus']['mode'], 'ocr')
        self.assertTrue(channel['sourceStatus']['complete'])
        self.assertEqual(channel['match']['ownSide'], 'right')  # pov.camp = red
        self.assertEqual(channel['match']['mode'], '王者峡谷—5v5')
        self.assertEqual(channel['match']['durationSec'], 1123)
        self.assertTrue(channel['match']['date'].endswith('-08-15'))
        self.assertEqual(channel['match']['session'], '录像补录')
        self.assertEqual(channel['match']['winner'], '')
        # 录屏加载页十人必须落进草稿（否则校对页是 10 个空行，等于没法审）。
        self.assertEqual(len(channel['sources']['video']['roster']), 10)
        draft_players = channel['draft']['players']
        self.assertEqual(len(draft_players), 10)
        self.assertEqual(sum(1 for player in draft_players if player.get('hero')), 10)
        self.assertTrue(any(player.get('nickname') for player in draft_players))
        self.assertTrue(channel['draft']['missing'])  # 录像没有终局十人字段
        summary = self.summary(channel['id'])
        self.assertEqual(summary['recordingShas'], [sha])
        self.assertEqual(summary['screenshotImageIds'], [])
        self.assertEqual(summary['recordingIds'], [recording_id])

        review = self.client.post(f"/api/channels/{channel['id']}/review",
                                  json={'reviewedBy': '教练乙'})
        self.assertEqual(review.status_code, 200, review.text)
        save = self.client.post(f"/api/channels/{channel['id']}/save",
                                json={'allowMissing': True})
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(len(save.json()['bundle']['players']), 10)

        again = self.client.post('/api/channels/from-recording',
                                 json={'recordingId': recording_id, 'session': '重复'})
        self.assertEqual(again.status_code, 409)

    def test_from_screenshots_rejects_multiple_groups(self):
        one = self.add_pages(['data'], date='2026-08-15')
        other = self.add_pages(['team'], date='2026-08-16')
        response = self.client.post('/api/channels/from-screenshots',
                                    json={'imageIds': one + other, 'session': '跨局截图'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('同一局', response.json()['detail'])

    def test_from_recording_without_report_is_409_and_incomplete_lineup_is_400(self):
        no_report_id, _ = self.write_recording(with_report=False)
        missing_report = self.client.post('/api/channels/from-recording',
                                          json={'recordingId': no_report_id, 'session': 'x'})
        self.assertEqual(missing_report.status_code, 409)
        self.assertIn('识别', missing_report.json()['detail'])

        partial_id, _ = self.write_recording(
            report=recording_report(full_lineup=False), sha='cd' * 32)
        partial = self.client.post('/api/channels/from-recording',
                                   json={'recordingId': partial_id, 'session': 'x'})
        self.assertEqual(partial.status_code, 400)
        self.assertIn('十人阵容', partial.json()['detail'])

        # 既没有日期也填 session/opponent 时同样要有可操作提示。
        unknown_date = recording_report()
        unknown_date.pop('match')
        unknown_id, _ = self.write_recording(report=unknown_date, sha='ef' * 32)
        empty = self.client.post('/api/channels/from-recording',
                                 json={'recordingId': unknown_id})
        self.assertEqual(empty.status_code, 400)
        self.assertIn('至少填写', empty.json()['detail'])

    # ---- 旧方式挂载的报告：录像身份三线索解析（task-4） --------------------
    def test_recording_identity_name_variants(self):
        recording_id, sha = self.write_recording(name='20261102_27-6_录屏.mp4')
        meta = recording_store.read_meta(recording_id)
        ident = recording_store.identity(meta)
        self.assertEqual(ident['id'], recording_id)
        self.assertEqual(ident['sha256'], sha)
        for name in (f'录像报告-{recording_id}.json',
                     '20261102_27-6_录屏报告.json',
                     '20261102_27-6_录屏_录屏报告.json',
                     '20261102_27-6_录屏.json'):
            self.assertIn(name, ident['names'])
        # 文件名线索能独立命中（旧数据没有 recordingId，sha 是报告 JSON 的）。
        self.assertEqual(recording_store.match_file(
            {'name': '20261102_27-6_录屏报告.json', 'sha256': 'fc80a1'}, [ident]), recording_id)
        self.assertEqual(recording_store.match_file(
            {'name': f'录像报告-{recording_id}.json', 'sha256': 'old'}, [ident]), recording_id)

    def test_old_style_report_matches_recording_badge_and_blocks_duplicate(self):
        recording_id, video_sha = self.write_recording(name='20261102_27-6_录屏.mp4')
        channel = self.create_channel(match={'date': '2026-11-02', 'session': '11/02 训练赛'})
        raw = json.dumps(recording_report(), ensure_ascii=False).encode('utf-8')
        attach = self.client.post(f"/api/channels/{channel['id']}/video",
                                  params={'name': '20261102_27-6_录屏报告.json'}, content=raw)
        self.assertEqual(attach.status_code, 200, attach.text)
        summary = self.summary(channel['id'])
        # 旧流程挂的是报告 JSON 的 sha，与视频 sha 不同；仍要按文件名认出录像。
        self.assertEqual(summary['recordingShas'], [hashlib.sha256(raw).hexdigest()])
        self.assertNotEqual(summary['recordingShas'], [video_sha])
        self.assertEqual(summary['recordingIds'], [recording_id])

        duplicate = self.client.post('/api/channels/from-recording',
                                     json={'recordingId': recording_id})
        self.assertEqual(duplicate.status_code, 409)
        detail = duplicate.json()['detail']
        self.assertIn('2026-11-02', detail)
        self.assertIn('11/02 训练赛', detail)

    def test_old_style_attachment_does_not_block_other_recordings(self):
        attached_id, _ = self.write_recording(name='20261102_27-6_录屏.mp4')
        other_id, _ = self.write_recording(name='20261103_18-3_录屏.mp4', sha='cd' * 32)
        channel = self.create_channel(match={'date': '2026-11-02', 'session': '11/02 训练赛'})
        attach = self.client.post(
            f"/api/channels/{channel['id']}/video",
            params={'name': '20261102_27-6_录屏报告.json'},
            content=json.dumps(recording_report(), ensure_ascii=False).encode('utf-8'))
        self.assertEqual(attach.status_code, 200, attach.text)
        self.assertEqual(self.summary(channel['id'])['recordingIds'], [attached_id])
        created = self.client.post('/api/channels/from-recording', json={
            'recordingId': other_id, 'session': '另一段录屏'})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()['entry']['primary'], 'video')

    # ---- d) 补采并集 / 幂等 / replace --------------------------------------
    def test_legacy_channel_without_official_becomes_ocr(self):
        """存量卡死通道修复：无 official、只有截图/录屏的旧通道按 OCR 识别并可入库。"""
        channel = self.create_channel()
        image_ids = self.add_pages(PAGE_TYPES)
        response = self.client.post(f"/api/channels/{channel['id']}/screenshot",
                                    json={'imageIds': image_ids})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['sourceStatus']['mode'], 'ocr')
        self.assertTrue(body['sourceStatus']['complete'])
        review = self.client.post(f"/api/channels/{channel['id']}/review",
                                  json={'reviewedBy': '教练丙'})
        self.assertEqual(review.status_code, 200, review.text)
        save = self.client.post(f"/api/channels/{channel['id']}/save")
        self.assertEqual(save.status_code, 200, save.text)
        self.assertTrue((server.MATCHES_DIR / f"channel-{channel['id']}.json").is_file())

    def test_screenshot_union_allows_supplement_and_replace(self):
        channel = self.create_channel()
        channel_id = channel['id']
        first = self.add_pages(['score', 'kda', 'data'])
        response = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': first})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sourceStatus']['statuses']['screenshot'], 'partial')
        self.assertFalse(response.json()['sourceStatus']['complete'])

        rest = self.add_pages(['output', 'survival', 'farming', 'team'])
        response = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': rest})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # 本次选择排在并集前面（同页型重传时新图值优先）。
        self.assertEqual(body['sources']['screenshot']['imageIds'], rest + first)
        self.assertEqual(body['sourceStatus']['statuses']['screenshot'], 'completed')
        self.assertTrue(body['sourceStatus']['complete'])

        # 同一组图重复 attach 幂等：并集不变、不 409。
        repeated = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': rest})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(len(repeated.json()['sources']['screenshot']['imageIds']), 7)

        # replace=true：只用本次选择替换本局截图。
        replacement = self.add_pages(['score', 'kda', 'data'])
        replaced = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': replacement, 'replace': True})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertEqual(replaced.json()['sources']['screenshot']['imageIds'], replacement)
        self.assertEqual(len(replaced.json()['sources']['screenshot']['imageIds']), 3)

    def test_union_reuploaded_pages_take_new_values(self):
        """整组重拍后补采：同一页型新图的值必须盖过旧图（先到先得，故新图在前）。"""
        channel = self.create_channel()
        channel_id = channel['id']
        old = self.add_pages(PAGE_TYPES, kills=2)
        first = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                 json={'imageIds': old})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['draft']['players'][0]['fields']['kills']['value'], 2)

        new = self.add_pages(PAGE_TYPES, kills=9)  # 同日期/比分，重拍后读数变化
        response = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': new})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['sources']['screenshot']['imageIds'], new + old)
        kills = {player['fields']['kills']['value'] for player in body['draft']['players']}
        self.assertEqual(kills, {9})

    def test_union_failure_keeps_old_pages_unless_replace(self):
        """并集跨局且本次页型不全时，不能把已挂的整组七页悄悄替换掉。"""
        channel = self.create_channel()
        channel_id = channel['id']
        old = self.add_pages(PAGE_TYPES, date='2026-08-15')
        attached = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': old})
        self.assertEqual(attached.status_code, 200, attached.text)

        other = self.add_pages(['data', 'output', 'team'], date='2026-08-16')
        response = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': other})
        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()['detail']
        self.assertIn('不是同一局', detail)
        self.assertIn('replace=true', detail)
        loaded = self.client.get(f"/api/channels/{channel_id}").json()
        self.assertEqual(loaded['sources']['screenshot']['imageIds'], old)
        self.assertEqual(loaded['sourceStatus']['statuses']['screenshot'], 'completed')

    def test_union_auto_replaces_only_complete_new_group(self):
        """本次选择本身是完整七页十人组（另一局）时，自动按替换处理。"""
        channel = self.create_channel()
        channel_id = channel['id']
        old = self.add_pages(PAGE_TYPES, date='2026-08-15')
        self.assertEqual(self.client.post(
            f'/api/channels/{channel_id}/screenshot', json={'imageIds': old}).status_code, 200)
        new = self.add_pages(PAGE_TYPES, date='2026-08-16', kills=5)
        response = self.client.post(f'/api/channels/{channel_id}/screenshot',
                                    json={'imageIds': new})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sources']['screenshot']['imageIds'], new)

    # ---- e) 回归：空营地通道仍需王者营地链接 -------------------------------
    def test_camp_channel_still_requires_official_link(self):
        channel = self.create_channel()
        self.assertEqual(channel['entry'], {'mode': '', 'primary': ''})
        loaded = self.client.get(f"/api/channels/{channel['id']}").json()
        self.assertEqual(loaded['sourceStatus']['mode'], 'camp')
        self.assertEqual(loaded['sourceStatus']['requiredSources'], ['official'])
        review = self.client.post(f"/api/channels/{channel['id']}/review",
                                  json={'reviewedBy': 'tester'})
        save = self.client.post(f"/api/channels/{channel['id']}/save")
        self.assertEqual(review.status_code, 400)
        self.assertEqual(save.status_code, 400)
        self.assertIn('王者营地', review.json()['detail'])
        self.assertFalse(server.MATCHES_DIR.exists())

    def test_create_channel_entry_validation(self):
        bad = self.client.post('/api/channels', json={
            'match': {'date': '2026-08-15'}, 'entry': {'mode': 'video'}})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('camp', bad.json()['detail'])
        self.assertIn('ocr', bad.json()['detail'])

        ocr = self.client.post('/api/channels', json={
            'match': {'date': '2026-08-15', 'session': '预建OCR通道'},
            'entry': {'mode': 'ocr'}})
        self.assertEqual(ocr.status_code, 200, ocr.text)
        channel = ocr.json()
        self.assertEqual(channel['entry']['mode'], 'ocr')
        loaded = self.client.get(f"/api/channels/{channel['id']}").json()
        self.assertEqual(loaded['sourceStatus']['mode'], 'ocr')
        self.assertFalse(loaded['sourceStatus']['complete'])
        self.assertIn('截图/录屏', loaded['sourceStatus']['missing'][0])


if __name__ == '__main__':
    unittest.main()
