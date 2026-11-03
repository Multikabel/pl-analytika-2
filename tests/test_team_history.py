import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
from app.team_views import team_detail, team_chart_context, team_ranking, STAT_COLUMNS
from app.referee_views import match_history, history_chart, streak_summary, render_history, CATEGORIES, COLORS


def observations():
    rows=[]
    for i in range(9):
        rows.append({'match_id':str(i),'season':'2026-27','Datum':pd.Timestamp('2026-08-01')+pd.Timedelta(days=i),
            '_time':pd.Timedelta(hours=15),'Čas':'15:00','Tým':'Arsenal','Soupeř':f'Team {i}',
            'venue':'H' if i%2 else 'A','Prostředí':'Doma' if i%2 else 'Venku', 'Výsledek':'2:1',
            **{f'{m} {p}': (i+1 if p=='PRO' else 10-i if p=='PROTI' else 11)
               for m in ['Fauly','Žluté karty','Rohy'] for p in ['PRO','PROTI','CELKEM']}})
    return pd.DataFrame(rows)


class TeamHistoryTests(unittest.TestCase):
    def prepare(self,d,metric='Fauly',perspective='PRO',environment='Vše',season='2026-27'):
        summary,_,history=team_detail(d,season,'Arsenal',perspective,environment)
        data=match_history(team_chart_context(history,perspective),f'{metric} {perspective}')
        return summary,data

    def test_all_filters_match_5a(self):
        d=observations()
        for metric in ['Fauly','Žluté karty','Rohy']:
            for perspective in ['PRO','PROTI','CELKEM']:
                for environment,n in [('Vše',9),('Doma',4),('Venku',5)]:
                    with self.subTest(metric=metric,perspective=perspective,environment=environment):
                        summary,x=self.prepare(d,metric,perspective,environment)
                        ref=summary.set_index('Statistika').loc[metric]
                        rank=team_ranking(d,'2026-27',metric,perspective,environment).iloc[0]
                        self.assertEqual(len(x),n)
                        self.assertEqual(len(x),ref['Platné N'])
                        self.assertEqual(x['Průměr'].iloc[0],rank['Průměr'])
                        spec=history_chart(x,metric,str)
                        self.assertEqual(spec['layer'][1]['data']['values'][0]['mean'],ref['Průměr'])

    def test_real_perspective_values_and_context(self):
        _,x=self.prepare(observations(),perspective='PROTI',environment='Venku')
        self.assertEqual(x.Hodnota.tolist(),[10,8,6,4,2])
        spec=history_chart(x,'Fauly',str)
        first=spec['layer'][0]['data']['values'][0]
        self.assertEqual((first['Domácí'],first['Hosté'],first['Výsledek']),('Team 0','Arsenal','1:2'))
        self.assertEqual((first['Tým'],first['Pohled'],first['Prostředí']),('Arsenal','PROTI','Venku'))

    def test_season_and_team_isolation(self):
        d=observations(); other=d.copy(); other['season']='2025-26'; other['Fauly PRO']=99
        rival=d.copy(); rival['Tým']='Chelsea'; rival['Fauly PRO']=88
        _,x=self.prepare(pd.concat([other,rival,d]))
        self.assertEqual(x.Hodnota.tolist(),list(range(1,10)))

    def test_venue_sequence_skips_other_environment(self):
        d=observations()
        for env,ids in [('Venku',['0','2','4','6','8']),('Doma',['1','3','5','7'])]:
            _,x=self.prepare(d,environment=env)
            self.assertEqual(x.match_id.tolist(),ids)
            self.assertEqual(streak_summary(x.Kategorie)['current'],(CATEGORIES[0],2))

    def test_missing_and_last_five(self):
        d=observations(); d.loc[7,'Fauly PRO']=None
        _,x=self.prepare(d)
        self.assertEqual(x.tail(5).match_id.tolist(),['3','4','5','6','8'])
        self.assertEqual(len(x),8)
        self.assertEqual(x['Průměr'].iloc[0],37/8)
        self.assertEqual(x.tail(5).Hodnota.mean(),6.2)

    def test_neutral_and_one_observation(self):
        for d in [observations(),observations().iloc[:1]]:
            _,x=self.prepare(d,perspective='CELKEM')
            self.assertEqual(set(x.Kategorie),{CATEGORIES[2]})
            s=streak_summary(x.Kategorie)
            self.assertIsNone(s[CATEGORIES[0]]['Nejdelší'])
            self.assertIsNone(s[CATEGORIES[1]]['Průměrná délka'])

    def test_order_axis_palette_tooltip(self):
        _,x=self.prepare(observations().iloc[::-1])
        spec=history_chart(x,'Fauly',str); bars=spec['layer'][0]
        self.assertEqual(bars['encoding']['y']['sort'],list(range(9)))
        self.assertFalse(bars['encoding']['y']['scale']['reverse'])
        self.assertEqual(bars['encoding']['color']['scale']['range'],COLORS)
        self.assertIn('Team 0 (V)',bars['encoding']['y']['axis']['labelExpr'])
        self.assertTrue({'Tým','Pohled','Prostředí','Výsledek','Domácí','Hosté','Kategorie'} <= {v['field'] for v in bars['encoding']['tooltip']})
        self.assertEqual(spec['height'],288)

    def test_empty_no_line_and_short_history(self):
        _,x=self.prepare(observations().iloc[:0])
        self.assertIsNone(history_chart(x,'Fauly',str))
        _,x=self.prepare(observations().iloc[:3])
        self.assertEqual(len(x.tail(5)),3)

    def test_unrounded_mean_and_series(self):
        d=pd.concat([observations()]*3,ignore_index=True).iloc[:21].copy()
        d['match_id']=[str(i) for i in range(21)]
        d['Datum']=pd.date_range('2026-01-01',periods=21)
        d['Fauly PRO']=[3]*20+[4]
        _,x=self.prepare(d)
        self.assertEqual(x.Kategorie.iloc[0],CATEGORIES[1])
        self.assertEqual(streak_summary(x.Kategorie)[CATEGORIES[1]]['Nejdelší'],20)

    def test_ui_uses_shared_renderer_and_correct_last_five(self):
        _,_,h=team_detail(observations(),'2026-27','Arsenal','PROTI','Venku')
        st=SimpleNamespace(info=Mock(),caption=Mock(),dataframe=Mock(),vega_lite_chart=Mock(),
                           column_config=SimpleNamespace(DateColumn=Mock(),NumberColumn=Mock()))
        render_history(st,team_chart_context(h,'PROTI'),'Fauly',str,value_column='Fauly PROTI')
        self.assertEqual(st.dataframe.call_args_list[0].args[0]['Hodnota'].tolist(),[10,8,6,4,2])
        self.assertEqual(st.vega_lite_chart.call_args.kwargs['theme'],'streamlit')
        self.assertIn('Prostředí',st.dataframe.call_args_list[0].args[0])


if __name__=='__main__': unittest.main()
