import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
from app.team_views import team_observations, filtered, league_reference, team_ranking, team_detail, render_teams


class TeamViewsTests(unittest.TestCase):
    def setUp(self):
        self.matches=pd.DataFrame([
            dict(match_id='1',season='2026-27',match_date='2026-08-02',kickoff_time='15:00',home_team='A',away_team='B',home_goals=2,away_goals=1),
            dict(match_id='2',season='2026-27',match_date='2026-08-03',kickoff_time='12:30',home_team='C',away_team='A',home_goals=0,away_goals=3),
            dict(match_id='3',season='2025-26',match_date='2025-08-01',kickoff_time='15:00',home_team='A',away_team='B',home_goals=1,away_goals=1)])
        rows=[]
        for m,values in zip(self.matches.to_dict('records'),[(10,20),(30,4),(50,60)]):
            for i,v in enumerate(['H','A']):
                rows.append(dict(match_id=m['match_id'],season=m['season'],venue=v,
                    team=m['home_team'] if i==0 else m['away_team'],opponent=m['away_team'] if i==0 else m['home_team'],
                    fouls_committed=values[i],yellow_cards=i+1,corners_for=i+3))
        self.teams=pd.DataFrame(rows)

    def data(self): return team_observations(self.matches,self.teams)

    def test_home_away_perspectives_all_metrics(self):
        d=self.data(); h=d[(d.match_id=='1') & (d.venue=='H')].iloc[0]; a=d[(d.match_id=='1') & (d.venue=='A')].iloc[0]
        for metric,x,y in [('Fauly',10,20),('Žluté karty',1,2),('Rohy',3,4)]:
            self.assertEqual([h[f'{metric} {p}'] for p in ['PRO','PROTI','CELKEM']],[x,y,x+y])
            self.assertEqual([a[f'{metric} {p}'] for p in ['PRO','PROTI','CELKEM']],[y,x,x+y])
        self.assertEqual(a['Výsledek'],'1:2')

    def test_filters_and_season(self):
        d=self.data()
        self.assertEqual(len(filtered(d,'2026-27','Vše')),4)
        self.assertEqual(filtered(d,'2026-27','Doma')['Tým'].tolist(),['A','C'])
        self.assertEqual(filtered(d,'2026-27','Venku')['Tým'].tolist(),['B','A'])
        self.assertEqual(len(filtered(d,'2025-26','Vše')),2)

    def test_summary(self):
        s,c,h=team_detail(self.data(),'2026-27','A','PRO','Vše')
        f=s.iloc[0]
        self.assertEqual([f[x] for x in ['Zápasy','Platné N','Součet','Průměr','Minimum','Maximum']],[2,2,14,7,4,10])
        self.assertEqual(c.iloc[0]['Liga'],16)
        self.assertEqual(c.iloc[0]['Rozdíl'],-9)

    def test_league_references_and_total_denominator(self):
        d=self.data()
        expected={'PRO':{'Vše':16,'Doma':20,'Venku':12},'PROTI':{'Vše':16,'Doma':12,'Venku':20},'CELKEM':dict.fromkeys(['Vše','Doma','Venku'],32)}
        for p,envs in expected.items():
            for e,mean in envs.items():
                r=league_reference(d,'2026-27','Fauly',p,e)
                self.assertEqual(r['Průměr'],mean)
                self.assertEqual(r['Platné N'],4 if p!='CELKEM' and e=='Vše' else 2)

    def test_missing_one_side_is_not_zero(self):
        self.teams.loc[0,'fouls_committed']=None
        d=self.data()
        a=d[(d.match_id=='1') & (d.venue=='A')].iloc[0]
        self.assertEqual(a['Fauly PRO'],20)
        self.assertTrue(pd.isna(a['Fauly PROTI']))
        self.assertTrue(pd.isna(a['Fauly CELKEM']))
        self.assertEqual(league_reference(d,'2026-27','Fauly','PRO','Vše')['Platné N'],3)
        self.assertEqual(league_reference(d,'2026-27','Fauly','CELKEM','Vše')['Platné N'],1)
        self.assertEqual(league_reference(d,'2026-27','Rohy','CELKEM','Vše')['Platné N'],2)

    def test_no_valid_values_sorted_last(self):
        self.teams.loc[2,'fouls_committed']=-1
        table=team_ranking(self.data(),'2026-27','Fauly','PRO','Vše')
        last=table.iloc[-1]
        self.assertEqual(last['Tým'],'C'); self.assertEqual(last['Zápasy'],1)
        self.assertEqual(last['Platné N'],0); self.assertTrue(pd.isna(last['Průměr']))

    def test_duplicate_and_conflicting(self):
        self.matches=pd.concat([self.matches,self.matches.iloc[[0]]])
        self.teams=pd.concat([self.teams,self.teams.iloc[[0]]])
        self.assertEqual(len(self.data()),6)
        conflict=self.teams.iloc[[0]].copy(); conflict['fouls_committed']=99
        self.teams=pd.concat([self.teams,conflict])
        self.assertEqual(len(self.data()),4)

    def test_unplayed_and_incomplete_pair(self):
        self.matches.loc[0,'home_goals']=None
        self.teams=self.teams[self.teams.match_id!='2'].copy()
        self.assertEqual(len(self.data()),2)

    def test_empty(self):
        d=team_observations(pd.DataFrame(),pd.DataFrame())
        self.assertTrue(team_ranking(d,'2026-27','Fauly','PRO','Vše').empty)
        self.assertTrue(pd.isna(league_reference(d,'2026-27','Fauly','PRO','Vše')['Průměr']))

    def test_tie_order_and_chronology(self):
        self.teams['fouls_committed']=10
        self.matches=self.matches.iloc[::-1]; self.teams=self.teams.iloc[::-1]
        d=self.data()
        self.assertEqual(team_ranking(d,'2026-27','Fauly','PRO','Vše')['Tým'].tolist(),['A','B','C'])
        self.assertEqual(team_detail(d,'2026-27','A','PRO','Vše')[2].match_id.tolist(),['1','2'])

    def test_missing_column_and_real_zero(self):
        self.teams=self.teams.drop(columns='yellow_cards')
        self.teams.loc[0,'fouls_committed']=0
        d=self.data()
        self.assertEqual(league_reference(d,'2026-27','Žluté karty','PRO','Vše')['Platné N'],0)
        self.assertEqual(team_detail(d,'2026-27','A','PRO','Doma')[0].iloc[0]['Průměr'],0)

    def test_detail_split_opponent_and_total(self):
        d=self.data()
        self.assertEqual(team_detail(d,'2026-27','A','PROTI','Doma')[0].iloc[0]['Průměr'],20)
        self.assertEqual(team_detail(d,'2026-27','A','PROTI','Venku')[0].iloc[0]['Průměr'],30)
        self.assertEqual(team_detail(d,'2026-27','A','CELKEM','Venku')[0].iloc[0]['Průměr'],34)

    def test_same_day_kickoff_order(self):
        self.matches.loc[1,'match_date']='2026-08-02'
        self.assertEqual(team_detail(self.data(),'2026-27','A','PRO','Vše')[2].match_id.tolist(),['2','1'])

    def test_ui_all_filters_and_all_history_columns(self):
        for p in ['PRO','PROTI','CELKEM']:
            for e in ['Vše','Doma','Venku']:
                st=SimpleNamespace(info=Mock(),caption=Mock(),dataframe=Mock(),vega_lite_chart=Mock(),
                    selectbox=Mock(side_effect=lambda label,opts,**k:opts[0]),
                    segmented_control=Mock(side_effect=lambda label,*a,**k:{'Statistika':'Rohy','Pohled':p,'Prostředí':e}[label]),
                    column_config=SimpleNamespace(NumberColumn=Mock(),DateColumn=Mock()))
                render_teams(st,self.matches,self.teams)
                self.assertEqual(st.dataframe.call_count,6)
                formats=[c.kwargs.get('format') for c in st.column_config.NumberColumn.call_args_list]
                self.assertIn('%+.1f',formats)
                self.assertNotIn('+%.1f',formats)
                st.vega_lite_chart.assert_called_once()
                self.assertEqual(len(st.dataframe.call_args.args[0].columns),13)
                self.assertEqual(st.dataframe.call_args_list[1].args[0]['Statistika'].tolist(),['Fauly','Žluté karty','Rohy'])


if __name__=='__main__': unittest.main()
