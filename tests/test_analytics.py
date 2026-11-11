import copy
import unittest

from analytics import aggregate_measures, player_measures, review_match, team_totals
from domain import POSITIONS, summarize


def fixture(duration=10):
    return {'id':'analytics-fixture','revision':1,'status':'confirmed','side':'right','winner':'right',
            'opponent':'对手','date':'2026-10-28','duration':str(duration),'scores':{'left':'5','right':'10'},
            'players':[{'side':side,'slot':i,'hero':f'英雄{i}','playerId':str(i) if side=='right' else '',
                        'position':POSITIONS[i], 'gold':str((i+1)*1000),'damage':str((i+1)*10000),
                        'taken':str((i+1)*5000),'kills':'2','deaths':'0','assists':'3'}
                       for side in ('left','right') for i in range(5)]}


class AnalyticsTests(unittest.TestCase):
    def test_weighted_minutes_use_only_valid_pairs(self):
        a,b,c = fixture(10),fixture(30),fixture(20)
        a['players'][5]['damage']='1000'
        b['players'][5]['damage']='9000'
        c['players'][5]['damage']=''
        rows=[(m,m['players'][5],True) for m in (a,b,c)]
        result=aggregate_measures(rows)
        self.assertEqual(result['damagePerMinute'],250)
        self.assertEqual(result['damagePerMinuteSamples'],2)
        self.assertEqual(result['damagePerMinuteMinutes'],40)
        b['duration']=''
        self.assertEqual(aggregate_measures(rows)['damagePerMinute'],100)

    def test_partial_team_does_not_create_share_or_total(self):
        m=fixture()
        m['players'][6]['damage']=''
        totals=team_totals(m,'right')
        self.assertIsNone(totals['damage']['value'])
        self.assertEqual(totals['damage']['samples'],4)
        row=player_measures(m,m['players'][5])
        self.assertIsNone(row['damageShare'])
        self.assertEqual(row['damagePerMinute'],1000)
        self.assertAlmostEqual(row['goldShare'],1000/15000*100)

    def test_role_filter_preserves_original_team_denominator(self):
        m=fixture()
        summary=summarize([m],[{'id':str(i),'name':f'队员{i}'} for i in range(5)],lambda p:p['position']=='对抗路')
        self.assertEqual(len(summary['heroes']),1)
        self.assertAlmostEqual(summary['heroes'][0]['damageShare'],10000/150000*100)
        self.assertEqual(summary['lineups'][0]['name'],'英雄0 / 英雄1 / 英雄2 / 英雄3 / 英雄4')

    def test_zero_deaths_and_missing_kda(self):
        m=fixture()
        self.assertEqual(player_measures(m,m['players'][5])['kda'],5)
        m['players'][5]['deaths']=''
        self.assertIsNone(player_measures(m,m['players'][5])['kda'])
        row=aggregate_measures([(m,m['players'][5],True)])
        self.assertIsNone(row['kda'])
        self.assertEqual(row['kdaSamples'],0)

    def test_kda_aggregates_counts_instead_of_average_ratios(self):
        a,b=fixture(),fixture()
        a['players'][5].update(kills='10',assists='0',deaths='1')
        b['players'][5].update(kills='0',assists='0',deaths='9')
        row=aggregate_measures([(a,a['players'][5],True),(b,b['players'][5],False)])
        self.assertEqual(row['kda'],1)
        self.assertEqual(row['kdaSamples'],2)

    def test_review_aligns_own_right_and_does_not_guess_positions(self):
        m=fixture()
        m['players'][5]['gold']='2000'
        r=review_match(m,[],'本队')
        self.assertEqual(r['order'],['right','left'])
        self.assertEqual(r['comparisons'][0]['difference'],1000)
        self.assertEqual(r['matchups'][0]['goldDifference'],1000)
        m['players'][5]['position']=''
        self.assertEqual(len(review_match(m,[],'本队')['matchups']),4)
        m['players'][5]['position']='打野'
        r=review_match(m,[],'本队')
        self.assertEqual(len(r['matchups']),3)
        self.assertTrue(r['warnings'])

    def test_zero_totals_do_not_divide_by_zero(self):
        m=fixture()
        for p in m['players']:
            p['damage']='0'
        self.assertIsNone(player_measures(m,m['players'][5])['damageShare'])
        self.assertEqual(team_totals(m,'right')['damage']['value'],0)
        m['duration']=''
        self.assertIsNone(player_measures(m,m['players'][5])['damagePerMinute'])

    def test_calculations_do_not_mutate_saved_record(self):
        m=fixture(); before=copy.deepcopy(m)
        review_match(m,[],'本队')
        summarize([m],[])
        self.assertEqual(m,before)
