import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
from app.referee_views import (match_history, streak_summary, history_chart, render_history,
                               summarize, detail_tables, season_rows, CATEGORIES, COLORS)


def history(values):
    return pd.DataFrame([{'match_id': str(i), 'Datum': pd.Timestamp('2026-08-01')+pd.Timedelta(days=i),
        '_time': pd.Timedelta(hours=15), 'Čas': '15:00', 'Výsledek': '1:0', 'season': '2026-27',
        'Domácí': 'Arsenal', 'Hosté': f'Team {i}', 'Rozhodčí': 'R',
        'Fauly': v, 'Žluté karty': 2, 'Rohy': 8} for i,v in enumerate(values)],
        columns=['match_id','Datum','_time','Čas','Výsledek','season','Domácí','Hosté','Rozhodčí','Fauly','Žluté karty','Rohy'])


class RefereeHistoryTests(unittest.TestCase):
    def test_chronology(self):
        h=history([2,4,6]).iloc[::-1]
        self.assertEqual(match_history(h,'Fauly').match_id.tolist(),['0','1','2'])

    def test_same_day_time(self):
        h=history([2,4]); h['Datum']=pd.Timestamp('2026-08-01')
        h.loc[0,'_time']=pd.Timedelta(hours=20)
        self.assertEqual(match_history(h,'Fauly').match_id.tolist(),['1','0'])

    def test_classes_reference_and_raw_precision(self):
        d=match_history(history([2,3,4]),'Fauly')
        self.assertEqual(d.Kategorie.tolist(),[CATEGORIES[1],CATEGORIES[2],CATEGORIES[0]])
        self.assertEqual(d['Průměr'].iloc[0],3)
        d=match_history(history([3]*20+[4]),'Fauly')
        self.assertEqual(round(d['Průměr'].iloc[0],1),3)
        self.assertEqual(d.Kategorie.iloc[0],CATEGORIES[1])

    def test_current_above(self):
        r=streak_summary([CATEGORIES[1],CATEGORIES[0],CATEGORIES[0]])
        self.assertEqual(r['current'],(CATEGORIES[0],2))

    def test_current_below(self):
        self.assertEqual(streak_summary([CATEGORIES[0],CATEGORIES[1],CATEGORIES[1]])['current'],(CATEGORIES[1],2))

    def test_longest_and_average_includes_current(self):
        a,b,_=CATEGORIES
        r=streak_summary([a,a,b,a,b,b,b,a,a,a])
        self.assertEqual(r[a],{'Nejdelší':3,'Průměrná délka':2})
        self.assertEqual(r[b],{'Nejdelší':3,'Průměrná délka':2})

    def test_neutral_breaks(self):
        a,b,n=CATEGORIES
        r=streak_summary([a,n,a,b,n,b,n])
        self.assertEqual(r[a]['Nejdelší'],1)
        self.assertEqual(r[b]['Nejdelší'],1)
        self.assertEqual(r['current'],(n,1))

    def test_missing_does_not_break(self):
        d=match_history(history([1,7,None,7]),'Fauly')
        self.assertEqual(len(d),3)
        self.assertEqual(streak_summary(d.Kategorie)['current'],(CATEGORIES[0],2))

    def test_last_five_valid(self):
        d=match_history(history([1,2,None,3,4,5,None,6,7]),'Fauly')
        self.assertEqual(d.tail(5).Hodnota.tolist(),[3,4,5,6,7])

    def test_short_history(self):
        self.assertEqual(len(match_history(history([1,None,2]),'Fauly').tail(5)),2)

    def test_empty(self):
        d=match_history(history([]),'Fauly')
        self.assertTrue(d.empty)
        self.assertIsNone(history_chart(d,'Fauly',str))
        self.assertIsNone(streak_summary([])['current'])

    def test_one(self):
        d=match_history(history([7]),'Fauly')
        self.assertEqual(d.Kategorie.tolist(),[CATEGORIES[2]])
        self.assertIsNone(streak_summary(d.Kategorie)[CATEGORIES[0]]['Nejdelší'])

    def test_metric_switch_and_4a_consistency(self):
        h=history([2,None,8])
        for metric in ['Fauly','Žluté karty','Rohy']:
            d=match_history(h,metric)
            s=summarize(h[metric])
            self.assertEqual(len(d),s['Platné N'])
            self.assertEqual(d['Průměr'].iloc[0],s['Průměr'])

    def test_season_referee_switch(self):
        h=history([2,4,8]); h.loc[1,'Rozhodčí']='S'; h.loc[2,'season']='2025-26'
        for season,ref,value in [('2026-27','R',2),('2026-27','S',4),('2025-26','R',8)]:
            _,_,selected=detail_tables(season_rows(h,season),ref)
            self.assertEqual(match_history(selected,'Fauly').Hodnota.tolist(),[value])

    def test_spec_order_colors_and_reference(self):
        d=match_history(history([2,4,6]).iloc[::-1],'Fauly')
        spec=history_chart(d,'Fauly',str)
        bars,line=spec['layer']
        self.assertEqual(bars['encoding']['y']['sort'],[0,1,2])
        self.assertFalse(bars['encoding']['y']['scale']['reverse'])
        self.assertEqual(bars['data']['values'][0]['Hosté'],'Team 0')
        self.assertEqual(bars['encoding']['color']['scale'],{'domain':CATEGORIES,'range':COLORS})
        self.assertEqual(line['data']['values'],[{'mean':4}])
        self.assertEqual(line['mark']['type'],'rule')
        self.assertNotIn('y',line['encoding'])
        self.assertNotIn('background',spec)
        json.dumps(spec,allow_nan=False)

    def test_heights_and_tooltips(self):
        for n in [5,15,25]:
            spec=history_chart(match_history(history(list(range(n))),'Fauly'),'Fauly',str)
            self.assertEqual(spec['height'],32*n)
            tooltip=spec['layer'][0]['encoding']['tooltip']
            self.assertTrue({'Datum','Čas','Domácí','Hosté','Výsledek','Rozhodčí','Hodnota','Průměr','Rozdíl','Kategorie'} <= {t['field'] for t in tooltip})

    def test_render_theme_and_absent_run_dash(self):
        st=SimpleNamespace(info=Mock(),caption=Mock(),dataframe=Mock(),vega_lite_chart=Mock(),
                           column_config=SimpleNamespace(DateColumn=Mock(),NumberColumn=Mock()))
        render_history(st,history([3]),'Fauly',str)
        self.assertEqual(st.vega_lite_chart.call_args.kwargs['theme'],'streamlit')
        runs=st.dataframe.call_args.args[0]
        self.assertEqual(runs['Nejdelší'].tolist(),['—','—'])
        self.assertEqual(runs['Průměrná délka'].tolist(),['—','—'])


if __name__=='__main__':
    unittest.main()
