"""Exercise actual UI helpers without network, scoring or archive writes."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


class Stopped(Exception):
    pass


class MatchSelectionTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((ROOT/'app/app.py').read_text(encoding='utf-8'))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                   {'load_current_round_view','clear_match_results','select_current_match'}]
        self.frame=pd.DataFrame([dict(home_team=f'H{i}',away_team=f'A{i}',match_date='2026-10-10',
                                      kickoff_time=f'{12+i}:00',played=False) for i in range(10)])
        self.st=SimpleNamespace(subheader=Mock(),warning=Mock(),caption=Mock(),session_state={},
                                stop=Mock(side_effect=Stopped),
                                selectbox=Mock(side_effect=lambda label,options,**kwargs:options[0]))
        self.ns=dict(st=self.st,pd=pd,season='2026-27',
                     H=pd.DataFrame(columns=['season','venue','team','opponent']),
                     load_fixtures=Mock(return_value=self.frame),
                     current_round=Mock(side_effect=lambda *a:(6,self.frame)),
                     sync_officials=Mock(),referee_for_match=Mock(return_value='P Tierney'))
        exec(compile(ast.Module(body=functions,type_ignores=[]),'match-helpers','exec'),self.ns)

    def select(self):
        return self.ns['select_current_match']()

    def test_sorted_identity_referee_and_same_source(self):
        self.frame=self.frame.iloc[::-1]
        result=self.select()
        self.assertEqual(result[:2],('H0','A0'))
        self.assertEqual(result[3:],('2026-27','P Tierney',6))
        self.assertEqual(str(result[2]),'2026-10-10')
        self.ns['load_fixtures'].assert_called_once_with('2026-27',auto_sync=False)
        self.ns['sync_officials'].assert_not_called()
        self.ns['referee_for_match'].assert_called_once_with('H0','A0',6)
        self.assertEqual(len(self.st.selectbox.call_args.args[1]),10)

    def test_unknown_referee(self):
        for missing in ['',None,float('nan')]:
            self.ns['referee_for_match'].return_value=missing
            self.assertEqual(self.select()[4],'')
            self.assertIn(unittest.mock.call('Rozhodčí: Zatím neurčen'),self.st.caption.call_args_list)

    def test_partial_and_missing_time(self):
        self.frame=self.frame.iloc[:9].copy()
        self.frame.loc[0,'kickoff_time']=None
        self.select()
        self.st.warning.assert_called_once()
        self.st.selectbox.return_value=('H0','A0')
        self.st.selectbox.side_effect=None
        self.select()
        self.assertIn('Čas neurčen',self.st.caption.call_args.args[0])

    def test_missing_date_stops_and_clears(self):
        self.frame.loc[0,'match_date']=None
        self.st.selectbox.side_effect=lambda *a,**k:('H0','A0')
        self.st.session_state['single']='stale'
        with self.assertRaises(Stopped): self.select()
        self.assertNotIn('single',self.st.session_state)

    def test_unavailable_and_empty_schedule(self):
        self.ns['load_fixtures'].side_effect=OSError('offline')
        with self.assertRaises(Stopped): self.select()
        self.ns['load_fixtures'].side_effect=None
        self.frame=self.frame.iloc[:0]
        with self.assertRaises(Stopped): self.select()

    def test_match_round_and_referee_change_clear_old_results(self):
        first=self.select()
        identity=(first[0],first[1],str(first[2]),*first[3:])
        for change in ['match','round','referee']:
            with self.subTest(change=change):
                self.st.session_state.update(single='old',single_identity=identity,
                                             pick_single_old='tip',single_team_filter='old',unrelated='keep')
                if change=='match': self.st.selectbox.side_effect=lambda *a,**k:('H1','A1')
                if change=='round': self.ns['current_round'].side_effect=lambda *a:(7,self.frame)
                if change=='referee': self.ns['referee_for_match'].return_value='A Taylor'
                self.select()
                self.assertNotIn('single',self.st.session_state)
                self.assertNotIn('pick_single_old',self.st.session_state)
                self.assertEqual(self.st.session_state['unrelated'],'keep')

    def test_same_identity_keeps_results(self):
        h,a,d,s,r,n=self.select()
        self.st.session_state.update(single='result',single_identity=(h,a,str(d),s,r,n))
        self.select()
        self.assertEqual(self.st.session_state['single'],'result')

    def test_sync_failure_keeps_cached_referee(self):
        self.ns['sync_officials'].side_effect=OSError('offline')
        self.assertEqual(self.select()[4],'P Tierney')


if __name__=='__main__':
    unittest.main()
