import unittest
from unittest.mock import patch
from analysis_data import AnalysisRepository


class TimelineSemanticsTests(unittest.TestCase):
    def run_process(self, duration, points, **values):
        repo = AnalysisRepository('unused','unused','unused')
        match={'key':'test','duration':duration,'ownCamp':'red','winnerCamp':None,'process':{'timeline':points},**values}
        with patch.object(repo,'_selected_matches',return_value=([match],[])):
            return repo.process({})

    def points(self,end=660):
        return [{'gameTime':t,'blueGold':1000+t,'redGold':1000+2*t} for t in range(0,end+1,60)]

    def test_no_fifteen_minute_extrapolation_in_short_game(self):
        value=self.run_process(693,self.points())
        entry=value['matches'][0]
        self.assertIsNone(entry['diffAt']['900'])
        self.assertIsNone(entry['phases']['mid'])
        self.assertEqual(entry['diffAt']['600'],600)
        self.assertEqual(value['aggregate']['landmarkSamples']['900'],0)
        self.assertEqual(entry['perspective'],'own-minus-enemy')

    def test_missing_ten_minute_is_not_classified_as_not_ahead(self):
        entry=self.run_process(480,self.points(480))['matches'][0]
        self.assertIsNone(entry['leadAt10'])

    def test_large_internal_gap_is_not_interpolated(self):
        points=[{'gameTime':t,'blueGold':1000+t,'redGold':1000} for t in (0,300,900,1200)]
        entry=self.run_process(1200,points)['matches'][0]
        self.assertIsNone(entry['diffAt']['600'])

    def test_unknown_result_never_counts_as_comeback(self):
        self.assertEqual(self.run_process(693,self.points())['aggregate']['comebacks'],0)

    def test_event_count_is_not_kill_count(self):
        value=self.run_process(693,self.points(),process={'timeline':self.points(),'killEvents':[{'delta':10}]*6})
        self.assertIsNone(value['matches'][0]['killsPerMinute'])

    def test_cumulative_kill_delta_uses_its_observation_window(self):
        points=self.points()
        for p in points:p.update(blueKills=p['gameTime']//60+2,redKills=3)
        self.assertEqual(self.run_process(693,points)['matches'][0]['killsPerMinute'],1)


if __name__=='__main__':unittest.main()
