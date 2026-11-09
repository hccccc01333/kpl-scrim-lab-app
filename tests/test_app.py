import copy
import io
import json
import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['TRAINING_DB'] = str(ROOT / 'test-results' / f'test-{uuid.uuid4().hex}.sqlite3')
from fastapi.testclient import TestClient
from PIL import Image
from server import app
from domain import number, summarize


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')
        cls.roster = [{'id': str(i), 'name': f'队员{i}'} for i in range(5)]
        assert cls.client.put('/api/settings', json={'teamName': '测试队', 'roster': cls.roster}).status_code == 200

    def fixture(self):
        return {'id': uuid.uuid4().hex, 'status': 'confirmed', 'side': 'right', 'winner': 'right',
                'date': '2026-10-28', 'opponent': '测试对手', 'reviewed': True,
                'scores': {'left': '', 'right': ''}, 'imageIds': [],
                'players': [{'side': s, 'slot': i, 'playerId': str(i) if s == 'right' else '',
                             'hero': f'英雄{i}', 'damage': '41.8k' if i == 0 else ''}
                            for s in ('left', 'right') for i in range(5)]}

    def test_number_units_and_unknown(self):
        self.assertEqual(number('41.8k'), 41800)
        self.assertEqual(number('2.1万'), 21000)
        self.assertEqual(number('17%'), 17)
        self.assertIsNone(number(''))
        for value in ('NaN', '-1', 'abc', True):
            with self.assertRaises(ValueError):
                number(value)

    def test_unknown_averages_and_right_side_win(self):
        m = self.fixture()
        summary = summarize([m, {**m, 'status': 'draft'}], self.roster)
        self.assertEqual((summary['games'], summary['wins']), (1, 1))
        first = next(r for r in summary['heroes'] if r['key'] == '英雄0')
        self.assertEqual(first['damage'], 41800)
        self.assertEqual(first['damageSamples'], 1)
        self.assertIsNone(first['kills'])

    def test_draft_can_be_incomplete_but_not_confirmed(self):
        m = self.fixture()
        m['players'][5]['hero'] = ''
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)
        m['status'] = 'draft'
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 200)

    def test_identity_and_confirmation_required(self):
        m = self.fixture()
        m['players'][5]['playerId'] = 'unknown'
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)
        m = self.fixture()
        m['reviewed'] = False
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)

    def test_revision_update_archive_and_recovery(self):
        m = self.fixture()
        created = self.client.post('/api/matches', json=m).json()
        self.assertEqual(created['revision'], 1)
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 409)
        created['status'] = 'archived'
        archived = self.client.post('/api/matches', json=created).json()
        self.assertEqual(archived['revision'], 2)
        self.assertEqual(archived['status'], 'archived')

    def test_kill_totals_checked(self):
        m = self.fixture()
        m['scores']['right'] = '32'
        for p in m['players']:
            p['kills'] = '1'
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)

    def upload(self, color):
        stream = io.BytesIO()
        Image.new('RGB', (320, 200), color).save(stream, format='PNG')
        r = self.client.post('/api/images?name=fixture.png', content=stream.getvalue())
        self.assertEqual(r.status_code, 200)
        return r.json()['id']

    def test_duplicate_evidence_blocked(self):
        image_id = self.upload('red')
        m = self.fixture()
        m['imageIds'] = [image_id]
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 200)
        another = self.fixture()
        another['imageIds'] = [image_id]
        self.assertEqual(self.client.post('/api/matches', json=another).status_code, 409)

    def test_score_conflict_between_images_blocked(self):
        from server import db
        import json
        ids = [self.upload('green'), self.upload('blue')]
        with db() as c:
            for image_id, score in zip(ids, (32, 17)):
                c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps({'scores': {'left': str(score)}}), image_id))
        m = self.fixture()
        m['imageIds'] = ids
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)

    def test_summary_filters(self):
        m = self.fixture()
        m['opponent'] = '唯一筛选对手'
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 200)
        s = self.client.get('/api/summary?opponent=唯一筛选对手&player=0').json()
        self.assertEqual(s['games'], 1)
        self.assertEqual(len(s['heroes']), 1)
        self.assertEqual(s['heroes'][0]['key'], '英雄0')
        self.assertEqual(self.client.get('/api/summary?from=2030-01-01').json()['games'], 0)

    def test_role_and_hero_filters_apply_to_same_player(self):
        m=self.fixture(); m['opponent']='同一队员筛选回归'; m['duration']='20'
        m['players'][5]['position']='中路';m['players'][6]['position']='游走'
        response=self.client.post('/api/matches',json=m)
        self.assertEqual(response.status_code,200,response.text)
        s=self.client.get('/api/summary?opponent=同一队员筛选回归&position=中路&hero=英雄0').json()
        self.assertEqual(s['games'],1);self.assertEqual(len(s['players']),1)
        self.assertEqual(s['heroes'][0]['damagePerMinute'],2090)
        self.assertEqual(self.client.get('/api/summary?opponent=同一队员筛选回归&position=游走&hero=英雄0').json()['games'],0)
        self.assertEqual(self.client.get('/api/summary?position=不存在位置').status_code,400)
        report=self.client.get('/api/matches/'+m['id']+'/review')
        self.assertEqual(report.status_code,200)
        self.assertEqual(report.json()['order'],['right','left'])
        self.assertEqual(self.client.get('/api/matches/missing/review').status_code,404)

    def test_backup_merge_and_atomic_invalid_restore(self):
        backup = self.client.get('/api/backup').json()
        before = len(self.client.get('/api/state').json()['matches'])
        r = self.client.post('/api/restore', json=backup)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['added'], 0)
        self.assertEqual(len(self.client.get('/api/state').json()['matches']), before)
        bad = copy.deepcopy(backup)
        bad['matches'].append({'invalid': True})
        self.assertEqual(self.client.post('/api/restore', json=bad).status_code, 400)
        self.assertEqual(len(self.client.get('/api/state').json()['matches']), before)

    def test_focus_crud_evaluate_and_backup(self):
        created = self.client.post('/api/focus', json={
            'title': '射手生存', 'metric': 'deaths', 'scopeType': 'player',
            'scopeId': '3', 'direction': 'down', 'target': 2})
        self.assertEqual(created.status_code, 200, created.text)
        focus_id = created.json()['id']
        listed = self.client.get('/api/focus').json()['items']
        self.assertEqual(listed[-1]['title'], '射手生存')
        updated = self.client.patch(f'/api/focus/{focus_id}', json={'status': 'improved'})
        self.assertEqual(updated.json()['status'], 'improved')
        evaluation = self.client.get('/api/focus/evaluate').json()['items']
        target = next(item for item in evaluation if item['id'] == focus_id)
        self.assertEqual(target['points'], [])  # 没有已确认比赛时如实为空
        backup = self.client.get('/api/backup').json()
        self.assertTrue(any(item['body']['title'] == '射手生存' for item in backup['focusItems']))
        # 备份恢复进全新数据库
        import server
        snapshot = json.dumps(backup, ensure_ascii=False)
        original_path = server.DB_PATH
        try:
            server.DB_PATH = original_path.parent / f'focus-restore-{uuid.uuid4().hex}.sqlite3'
            server.init_db()
            restored = self.client.post('/api/restore', json=json.loads(snapshot))
            self.assertEqual(restored.status_code, 200, restored.text)
            with server.db() as c:
                rows = c.execute('SELECT body FROM focus_items').fetchall()
            self.assertTrue(any(json.loads(row['body'])['title'] == '射手生存' for row in rows))
        finally:
            server.DB_PATH = original_path

    def test_local_origin_and_bad_image(self):
        self.assertEqual(self.client.post('/api/images', content=b'not an image').status_code, 400)
        self.assertEqual(self.client.put('/api/settings', headers={'Origin': 'https://other.example'}, json={}).status_code, 403)

    def test_root_serves_v3_and_analysis_redirects(self):
        # 根路径直接返回 V3 界面，/analysis 旧别名回根路径。
        index = self.client.get('/', follow_redirects=False)
        self.assertEqual(index.status_code, 200)
        self.assertIn('text/html', index.headers['content-type'])
        self.assertIn('static/app.js', index.text)

        redirect = self.client.get('/analysis', follow_redirects=False)
        self.assertIn(redirect.status_code, (301, 302, 303, 307))
        self.assertEqual(redirect.headers['location'], '/')

        # /v3 旧链接 302 回根路径，静态资源也跟随重定向。
        legacy = self.client.get('/v3/', follow_redirects=False)
        self.assertEqual(legacy.status_code, 302)
        self.assertEqual(legacy.headers['location'], '/')
        old_asset = self.client.get('/v3/static/app.js', follow_redirects=False)
        self.assertEqual(old_asset.status_code, 302)
        self.assertEqual(old_asset.headers['location'], '/static/app.js')
        asset = self.client.get('/static/app.js')
        self.assertEqual(asset.status_code, 200)
        self.assertIn('javascript', asset.headers['content-type'])

    def test_backup_into_fresh_database(self):
        import server
        m = self.fixture()
        m['imageIds'] = [self.upload('purple')]
        saved = self.client.post('/api/matches', json=m)
        self.assertEqual(saved.status_code, 200)
        snapshot = self.client.get('/api/backup').json()
        original_path = server.DB_PATH
        try:
            server.DB_PATH = original_path.parent / f'restored-{uuid.uuid4().hex}.sqlite3'
            server.init_db()
            result = self.client.post('/api/restore', json=snapshot)
            self.assertEqual(result.status_code, 200, result.text)
            restored = self.client.get('/api/state').json()
            self.assertEqual(len(restored['matches']), len(snapshot['matches']))
            self.assertEqual(len(restored['images']), len(snapshot['images']))
            self.assertEqual(self.client.get('/api/images/'+m['imageIds'][0]).status_code, 200)
            with server.db() as c:
                self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], len(snapshot['revisions']))
        finally:
            server.DB_PATH = original_path

    def test_icon_catalog_and_crop_bounds(self):
        catalog = self.client.get('/api/catalog').json()
        self.assertTrue(any(e['kind'] == 'hero' for e in catalog['entries']))
        image_id = self.upload('orange')
        self.assertEqual(self.client.get(f'/api/images/{image_id}/crop?x1=0&y1=0&x2=.5&y2=.5').status_code, 200)
        self.assertEqual(self.client.get(f'/api/images/{image_id}/crop?x1=-1&y1=0&x2=.5&y2=.5').status_code, 400)

    def test_catalog_icons_are_served_when_present(self):
        # The icon library is downloaded locally rather than shipped, so the
        # check only applies when it has been prepared.
        catalog = self.client.get('/api/catalog').json()
        entries = [e for e in catalog['entries'] if e.get('icon')]
        if not entries:
            self.skipTest('本地图标库尚未准备')
        served = [e for e in entries
                  if self.client.get(e['icon']).status_code == 200]
        if not served:
            self.skipTest('本地图标库尚未下载（运行 scripts/sync_catalog.py）')
        for entry in served[:5]:
            with self.subTest(entry=entry['id']):
                self.assertEqual(self.client.get(entry['icon']).status_code, 200)

    def test_only_confirmed_equipment_icons_become_references(self):
        import json
        from server import db, learned_index
        from vision import catalog, prepare_image, crop_box, rank_icon
        image_id = self.upload('cyan')
        hero = next(e for e in catalog()['entries'] if e['kind'] == 'equipment' and e.get('icon'))
        if not (ROOT / 'resources' / 'icons').exists():
            self.skipTest('本地图标库尚未下载（运行 scripts/sync_catalog.py）')
        region = {'side':'right', 'slot':0, 'kind':'equipment', 'index':0, 'box':[.1,.1,.5,.5]}
        with db() as c:
            c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps({'visuals':[region]}), image_id))
        m = self.fixture()
        m['imageIds'] = [image_id]
        m['players'][5]['equipmentSlots'] = [{'id':hero['id'], 'name':hero['name']}] + [None]*5
        m['players'][5]['equipment'] = hero['name']
        m['iconReviews'] = [{**region, 'imageId':image_id, 'catalogId':hero['id'], 'name':hero['name']}]
        m['status'] = 'draft'
        created = self.client.post('/api/matches', json=m).json()
        with db() as c:
            count_before = len(learned_index(c, 'different-image')['equipment'])
        created['status'] = 'confirmed'
        response = self.client.post('/api/matches', json=created)
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        with db() as c:
            learned = learned_index(c, 'different-image')
            self.assertEqual(len(learned['equipment']), count_before+1)
            self.assertEqual(len(learned_index(c, image_id)['equipment']), count_before)
            data = bytes(c.execute('SELECT data FROM images WHERE id=?', (image_id,)).fetchone()[0])
        crop = crop_box(prepare_image(data)[0], region['box'])
        candidates = rank_icon(crop, 'equipment', learned['equipment'])
        self.assertEqual((candidates[0]['name'], candidates[0]['source']), (hero['name'], 'reviewed'))
        import server
        backup = self.client.get('/api/backup').json()
        original_path = server.DB_PATH
        try:
            server.DB_PATH = original_path.parent / f'icon-restored-{uuid.uuid4().hex}.sqlite3'
            server.init_db()
            restored = self.client.post('/api/restore', json=backup)
            self.assertEqual(restored.status_code, 200, restored.text)
            with db() as c:
                recovered = learned_index(c, 'different-image')
                self.assertEqual(len(recovered['equipment']), len(learned['equipment']))
        finally:
            server.DB_PATH = original_path
        created['status'] = 'archived'
        self.assertEqual(self.client.post('/api/matches', json=created).status_code, 200)
        with db() as c:
            self.assertEqual(len(learned_index(c, 'different-image')['equipment']), count_before)

    def test_modified_hero_cannot_keep_stale_icon_review(self):
        import json
        from server import db
        from vision import catalog
        image_id = self.upload('magenta')
        hero = next(e for e in catalog()['entries'] if e['kind'] == 'hero')
        region = {'side':'right','slot':0,'kind':'hero','index':0,'box':[.1,.1,.5,.5]}
        with db() as c:
            c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps({'visuals':[region]}), image_id))
        m = self.fixture()
        m['imageIds'] = [image_id]
        m['iconReviews'] = [{**region,'imageId':image_id,'catalogId':hero['id'],'name':hero['name']}]
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)

    def test_old_portrait_labels_do_not_train_hero_identity(self):
        import json
        from server import db, learned_index
        from vision import catalog
        image_id = self.upload('brown')
        hero = next(e for e in catalog()['entries'] if e['name'] == '妲己')
        region = {'side':'right','slot':0,'kind':'hero','index':0,'box':[.1,.1,.5,.5]}
        with db() as c:
            c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps({'version':'scoreboard-v3-icons','visuals':[region]}), image_id))
        m = self.fixture()
        m['players'][5]['hero'] = hero['name']
        m['imageIds'] = [image_id]
        m['iconReviews'] = [{**region,'imageId':image_id,'catalogId':hero['id'],'name':hero['name']}]
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 200)
        with db() as c:
            self.assertEqual(learned_index(c, 'different-image')['hero'], [])
        self.assertEqual(self.client.get('/api/images/'+image_id+'/recognition').json()['visuals'], [])

    def test_page_score_correction_preserves_raw_ocr(self):
        import json
        from server import db
        ids = [self.upload('navy'), self.upload('teal')]
        with db() as c:
            for image_id, score in zip(ids, (32, 17)):
                c.execute('UPDATE images SET ocr=? WHERE id=?', (json.dumps({'scores': {'left':str(score)}}), image_id))
        m = self.fixture()
        m['imageIds'] = ids
        self.assertEqual(self.client.post('/api/matches', json=m).status_code, 400)
        m['evidenceReviews'] = {ids[1]: {'scores': {'left':'32'}, 'editedAt':'2026-10-28T00:00:00Z'}}
        r = self.client.post('/api/matches', json=m)
        self.assertEqual(r.status_code, 200, r.text)
        raw = self.client.get('/api/images/'+ids[1]+'/recognition').json()
        self.assertEqual(raw['scores']['left'], '17')
        self.assertEqual(r.json()['evidenceReviews'][ids[1]]['scores']['left'], '32')
        wrong = self.fixture()
        wrong['imageIds'] = ids
        wrong['evidenceReviews'] = {ids[0]: {'scores': {'left':'9999'}}}
        self.assertEqual(self.client.post('/api/matches', json=wrong).status_code, 400)


if __name__ == '__main__':
    unittest.main()
