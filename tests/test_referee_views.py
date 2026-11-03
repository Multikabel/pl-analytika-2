import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
from app.referee_views import match_statistics, summarize, ranking, detail_tables, season_rows, render_referees


class RefereeViewsTests(unittest.TestCase):
    def setUp(self):
        self.matches=pd.DataFrame([dict(match_id=str(i),season='2026-27' if i<3 else '2025-26',
            match_date=f'2026-08-{10+i:02}',home_team=f'H{i}',away_team=f'A{i}',
            home_goals=1,away_goals=0,referee=['R','R','S',''][i]) for i in range(4)])
        self.teams=pd.DataFrame([dict(match_id=str(i),season=self.matches.iloc[i].season,
            venue=v,team=f'H{i}' if v=='H' else f'A{i}',opponent=f'A{i}' if v=='H' else f'H{i}',
            fouls_committed=i+1,yellow_cards=1,corners_for=3) for i in range(4) for v in ['H','A']])

    def data(self):
        return match_statistics(self.matches,self.teams)

    def test_summary(self):
        self.assertEqual(summarize(pd.Series([2,4,None])),
                         {'Platné N':2,'Součet':6,'Průměr':3,'Minimum':2,'Maximum':4})

    def test_three_totals(self):
        d=self.data()
        self.assertEqual(d.Fauly.tolist(),[2,4,6,8])
        self.assertEqual(d['Žluté karty'].tolist(),[2]*4)
        self.assertEqual(d.Rohy.tolist(),[6]*4)

    def test_ranking_season(self):
        t=ranking(season_rows(self.data(),'2026-27'),'Fauly')
        self.assertEqual(t['Rozhodčí'].tolist(),['S','R'])
        self.assertEqual(t['Zápasy'].tolist(),[1,2])
        self.assertEqual(t['Průměr'].tolist(),[6,3])

    def test_league_weighted_includes_unknown(self):
        summary,comparison,history=detail_tables(self.data(),'R')
        self.assertEqual(comparison.iloc[0]['Liga'],5)
        self.assertEqual(comparison.iloc[0]['Rozdíl'],-2)
        self.assertEqual(comparison.iloc[0]['N liga'],4)
        self.assertEqual(len(ranking(self.data(),'Fauly')),2)

    def test_missing_stat_denominator_only(self):
        self.teams.loc[0,'fouls_committed']=None
        r=ranking(self.data(),'Fauly').set_index('Rozhodčí').loc['R']
        self.assertEqual(r['Zápasy'],2)
        self.assertEqual(r['Platné N'],1)
        self.assertEqual(r['Průměr'],4)
        self.assertEqual(summarize(self.data()['Rohy'])['Platné N'],4)

    def test_invalid_and_unplayed(self):
        self.matches.loc[0,'home_goals']=None
        self.teams.loc[2,'yellow_cards']=-1
        self.teams['corners_for']=self.teams.corners_for.astype(object)
        self.teams.loc[4,'corners_for']='invalid'
        d=self.data()
        self.assertEqual(len(d),3)
        self.assertEqual(summarize(d['Žluté karty'])['Platné N'],2)
        self.assertEqual(summarize(d.Rohy)['Platné N'],2)

    def test_duplicates(self):
        self.matches=pd.concat([self.matches,self.matches.iloc[[0]]])
        self.teams=pd.concat([self.teams,self.teams.iloc[[0]]])
        self.assertEqual(len(self.data()),4)
        conflicting=self.matches.iloc[[0]].copy(); conflicting['referee']='Other'
        self.matches=pd.concat([self.matches,conflicting])
        self.assertEqual(len(self.data()),3)

    def test_chronology(self):
        self.matches=self.matches.iloc[::-1]; self.teams=self.teams.iloc[::-1]
        _,_,history=detail_tables(self.data(),'R')
        self.assertEqual(history.match_id.tolist(),['0','1'])

    def test_empty_incomplete(self):
        self.assertTrue(match_statistics(pd.DataFrame(),pd.DataFrame()).empty)
        self.teams=self.teams.iloc[1:]
        self.assertEqual(len(self.data()),3)
        self.assertTrue(ranking(season_rows(self.data(),'none'),'Fauly').empty)

    def test_no_values_not_zero(self):
        result=summarize(pd.Series([None,'bad',-1]))
        self.assertEqual(result['Platné N'],0)
        self.assertIsNone(result['Součet'])
        self.assertTrue(pd.isna(result['Průměr']))

    def test_ui_tables_for_all_metrics(self):
        for metric in ['Fauly','Žluté karty','Rohy']:
            st=SimpleNamespace(selectbox=Mock(side_effect=lambda label,options,**k:options[0]),
                segmented_control=Mock(return_value=metric),caption=Mock(),info=Mock(),dataframe=Mock(),
                column_config=SimpleNamespace(NumberColumn=Mock(),DateColumn=Mock()))
            render_referees(st,self.matches,self.teams,lambda x:x,lambda x:x)
            self.assertEqual(st.dataframe.call_count,4)
            self.assertEqual(st.selectbox.call_args_list[0].args[1],['2026-27','2025-26'])
            st.info.assert_not_called()


if __name__=='__main__':
    unittest.main()
