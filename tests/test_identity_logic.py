import unittest
from identity_rules import validate_alias_conflicts
from tests.test_bp_input import BpInputTests


class IdentityLogicTests(BpInputTests):
    def test_bound_alias_retains_original_statistics(self):
        import sqlite3,json
        with sqlite3.connect(self.db) as c:
            settings=json.loads(c.execute('SELECT body FROM settings').fetchone()[0])
            settings['aliases']={'李白': settings['roster'][0]['id']}
            c.execute('UPDATE settings SET body=?',(json.dumps(settings),))
        result=self.client.get('/api/studio/identity').json()
        original=next(item for item in result['identities'] if item['label']=='李白')
        self.assertEqual(original['matches'],1)
        self.assertEqual(original['rows'],1)
        self.assertNotIn('李白',[item['label'] for item in result['unbound']])

    def test_alias_is_scoped_to_own_camp(self):
        from analysis_data import AnalysisRepository
        match={'ownCamp':'blue','players':[
            {'label':'同名','camp':'blue','playerId':None},
            {'label':'同名','camp':'red','playerId':None},
        ]}
        AnalysisRepository._apply_aliases([match], {'同名':'p1'}, {'p1':'正式昵称'})
        own,opponent=match['players']
        self.assertEqual(own['playerId'],'p1')
        self.assertTrue(own['bound'])
        self.assertIsNone(opponent['playerId'])
        self.assertFalse(opponent.get('bound'))
        validate_alias_conflicts([match], [{'id':'p1','name':'正式昵称'}], {'同名':'p1'}, {})

    def test_same_game_conflict_and_separate_game_alias(self):
        roster=[{'id':'p1','name':'正式昵称'}]
        game={'players':[{'label':'昵称甲'},{'label':'昵称乙'}]}
        with self.assertRaisesRegex(ValueError,'同一局'):
            validate_alias_conflicts([game],roster,{'昵称甲':'p1','昵称乙':'p1'}, {})
        validate_alias_conflicts([{'players':[{'label':'昵称甲'}]},{'players':[{'label':'昵称乙'}]}],roster,{'昵称甲':'p1','昵称乙':'p1'}, {})
        validate_alias_conflicts([{'players':[{'label':'正式昵称','rawLabel':'昵称甲','playerId':'p1'},{'label':'昵称乙'}]}],roster,{'昵称乙':'p1'}, {'昵称甲':'p1'})
