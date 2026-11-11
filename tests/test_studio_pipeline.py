import copy
import json
import math
import os
import sqlite3
import unittest
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import Response

from studio_api import create_studio_router
from studio_pipeline import DatasetStore, identify, prepare
from studio_research import research
from tests.test_analysis_data import make_db


def player(game, slot=0, camp='blue', **values):
    return {'matchKey':str(game),'playerKey':f'p{slot}','label':f'选手 {slot}','bound':True,
            'hero':f'英雄 {slot}','camp':camp,'date':f'2026-10-{int(game):02d}',
            'dateFull':True,'dateKey':f'2026-10-{int(game):02d}', 'position':'中路',
            'gold':10000+int(game)*100+slot,'damage':20000+slot*100,'taken':15000,
            'kills':2,'deaths':1,'assists':3,'participation':50,'source':'db',
            'minutes':20,'duration':1200,'partial':False,'full':True,'isOwn':True,
            'result':'win','opponent':'对手','session':'晚训',**values}


class CleaningTests(unittest.TestCase):
    def test_source_unchanged_and_invalid_is_not_zero(self):
        rows=[player(1,gold=-1,participation=150),player(2)]
        original=copy.deepcopy(rows)
        result=prepare(rows)
        self.assertEqual(rows,original)
        self.assertIsNone(result['rows'][0]['gold'])
        self.assertIsNone(result['rows'][0]['participation'])
        self.assertEqual(result['after']['invalidCells'],0)
        self.assertGreater(result['before']['invalidCells'],0)
        self.assertIsNone(result['rows'][0]['gpm'])

    def test_manual_correction_recalculates_metrics_and_has_log(self):
        rows=[player(1)]
        result=prepare(rows,edits=[{'rowId':identify(rows)[0]['_rowId'],'field':'gold','value':20000,'reason':'原图校正'}])
        self.assertEqual(result['rows'][0]['gpm'],1000)
        self.assertTrue(any(x['action']=='edit' and x['reason']=='原图校正' for x in result['logs']))
        self.assertTrue(any(x['action']=='recompute' and x['field']=='gpm' for x in result['logs']))

    def test_required_missing_exclusion_and_dedup(self):
        rows=[player(1),player(1,matchKey='copy'),player(2,gold=None)]
        result=prepare(rows,{'deduplicate':True,'dropMissing':True,'required':['gold']})
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['before']['rows'],3)
        self.assertTrue(any(x['action']=='fold-content' for x in result['logs']))

    def test_nonfinite_values_remain_exportable(self):
        result=prepare([player(1,gold=float('inf'))])
        json.dumps(result,allow_nan=False)
        self.assertEqual(result['after']['invalidCells'],0)

    def test_cannot_edit_identity_or_negative_count(self):
        rows=[player(1)];row_id=identify(rows)[0]['_rowId']
        for field,value in [('isOwn',True),('matchKey','fake'),('kills',-1)]:
            with self.assertRaises(ValueError):
                prepare(rows,edits=[{'rowId':row_id,'field':field,'value':value}])


class ResearchTests(unittest.TestCase):
    def test_hero_hhi_matches_reference_formula(self):
        result=research([player(g,hero='甲' if g<=3 else '乙') for g in range(1,5)],'hero_pool')
        row=result['rows'][0]
        self.assertEqual(row['hhi'],.625)
        self.assertEqual(row['effectiveHeroes'],1.6)
        self.assertEqual(row['topShare'],75)

    def test_same_position_hero_percentiles(self):
        rows=[player(g,slot=g,hero='同一英雄',damage=g) for g in range(1,6)]
        result=research(rows,'hero_benchmark')
        best=next(r for r in result['rows'] if r['value']==5)
        self.assertEqual(best['percentile'],100)
        self.assertEqual(best['p50'],3)
        self.assertEqual(best['referencePlayers'],5)

    def test_pair_requires_stable_ids(self):
        rows=[player(g,s,bound=False) for g in range(1,5) for s in range(5)]
        self.assertEqual(research(rows,'player_pairs')['rows'],[])
        for r in rows:r['bound']=True
        result=research(rows,'player_pairs')
        self.assertTrue(result['rows'])
        self.assertEqual(result['rows'][0]['n'],4)

    def test_no_time_extrapolation_and_missing_gap(self):
        # 王者三段口径（0-4 / 4-10 / 10+）后字段从 gold5/gold15 改为 gold4/goldEnd；
        # 语义不变：相邻观测点间隔 600s > 120s 时不插值、不把短片段外推到十分钟。
        rows=[player(1)]
        match={'key':'1','ownCamp':'blue','process':{'timeline':[
            {'gameTime':0,'blueGold':100,'redGold':100},
            {'gameTime':600,'blueGold':1000,'redGold':500}]}}
        result=research(rows,'tempo',matches=[match])
        row=result['rows'][0]
        self.assertIsNone(row['gold4'])
        self.assertIsNone(row['earlyDelta'])
        self.assertIsNone(row['midDelta'])
        self.assertEqual(row['gold10'],500)
        self.assertEqual(row['goldEnd'],500)
        self.assertEqual(result['summary']['十分钟领先且有赛果'],0)

    def test_swing_window_keeps_evidence(self):
        match={'key':'1','ownCamp':None,'process':{'timeline':[
            {'gameTime':t,'blueGold':1000+t*10,'redGold':1000} for t in (0,60,120)]}}
        result=research([player(1)],'swing_windows',matches=[match])
        self.assertEqual(result['rows'][0]['goldChange'],1200)
        self.assertEqual(result['rows'][0]['matchKey'],'1')


class PipelineApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(os.environ.get('STUDIO_TEST_ROOT',Path(__file__).resolve().parents[1]/'test-results'))/('pipeline-'+uuid.uuid4().hex)
        root.mkdir(parents=True)
        cls.db=root/'training.sqlite3';make_db(cls.db)
        cls.results=root/'research.sqlite3'
        app=FastAPI();app.include_router(create_studio_router(cls.db,root/'matches',root/'imports',cls.results))
        app.state.source_backup=lambda:Response(json.dumps({'schema':1,'matches':[]}),media_type='application/json')
        app.state.source_restore=lambda value:{'added':0,'skipped':0}
        cls.client=TestClient(app)
        cls.spec={'source':{'dataset':'records','filters':{'includePartial':True}},'rules':{'deduplicate':True}}

    def test_preview_publish_analyze_one_dataset(self):
        preview=self.client.post('/api/studio/clean/preview',json=self.spec)
        self.assertEqual(preview.status_code,200,preview.text)
        fingerprint=preview.json()['sourceFingerprint']
        published=self.client.post('/api/studio/datasets',json={**self.spec,'title':'晚训校对版','sourceFingerprint':fingerprint})
        self.assertEqual(published.status_code,200,published.text)
        dataset_id=published.json()['id']
        result=self.client.post('/api/studio/run',json={'dataset':'prepared:'+dataset_id,'filters':{'includePartial':True},'metrics':['gold']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'ok')
        topic=self.client.post('/api/studio/research',json={'dataset':'prepared:'+dataset_id,'filters':{'includePartial':True},'topic':'hero_pool'})
        self.assertEqual(topic.status_code,200)
        self.assertEqual(topic.json()['status'],'ok')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM matches').fetchone()[0],2)

    def test_stale_source_cannot_publish(self):
        result=self.client.post('/api/studio/datasets',json={**self.spec,'title':'旧快照','sourceFingerprint':'stale'})
        self.assertEqual(result.status_code,409)

    def test_dataset_backup_restore_and_tamper_check(self):
        store=DatasetStore(self.results)
        store.save('备份测试',prepare([player(1)]),{})
        backup=store.backup()
        self.assertEqual(store.restore(backup)['added'],0)
        altered=copy.deepcopy(backup);altered[0]['body']['rows'][0]['gold']=9876
        with self.assertRaises(ValueError):store.restore(altered)

    def test_legacy_dataset_without_exploratory_keeps_workspace_alive(self):
        """旧版/手工编辑的备份可能缺 exploratory；restore 不校验该字段，
        list() 曾硬取 body['exploratory'] 导致 /api/studio/workspace 500，
        整个工作台只剩「无法连接本地服务」。"""
        store=DatasetStore(self.results)
        saved=store.save('旧版备份缺字段',prepare([player(1)]),{})
        item=next(x for x in store.backup() if x['id']==saved['id'])
        body=item['body']
        body.pop('exploratory',None)
        with store.connect() as c:
            c.execute('UPDATE prepared_datasets SET body=? WHERE id=?',
                      (json.dumps(body,ensure_ascii=False),item['id']))
        listed={x['id']:x for x in store.list()}
        self.assertIn(item['id'],listed)
        self.assertFalse(listed[item['id']]['exploratory'])
        self.assertEqual(listed[item['id']]['after']['rows'],1)
        response=self.client.get('/api/studio/workspace')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsInstance(response.json()['datasets'],list)

    def test_topic_report_save(self):
        spec={'topic':'hero_pool','dataset':'records','filters':{'includePartial':True}}
        result=self.client.post('/api/studio/research',json=spec).json()
        saved=self.client.post('/api/studio/reports',json={'spec':spec,'title':'训练赛英雄池','fingerprint':result['meta']['fingerprint']})
        self.assertEqual(saved.status_code,200,saved.text)
        backup=self.client.get('/api/studio/backup').json()
        self.assertIn('datasets',backup)
        self.assertEqual(self.client.post('/api/studio/restore',json=backup).status_code,200)

    def test_unified_backup_handles_original_response_and_rejects_paths(self):
        backup=self.client.get('/api/studio/project-backup')
        self.assertEqual(backup.status_code,200,backup.text)
        self.assertIn('studio',backup.json())
        self.assertIn('analysisBundles',backup.json())
        self.assertEqual(self.client.post('/api/studio/project-restore',json=backup.json()).status_code,200)
        invalid={**backup.json(),'analysisBundles':[{'name':'../outside.json','body':{'schema':'kpl-match-data-v1'}}]}
        self.assertEqual(self.client.post('/api/studio/project-restore',json=invalid).status_code,400)


if __name__=='__main__':unittest.main()
