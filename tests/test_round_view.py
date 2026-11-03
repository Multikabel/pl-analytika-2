"""Execute the actual round branch with network/persistence disabled."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class RoundViewTests(unittest.TestCase):
    def render(self, frame, referee=lambda *args: ''):
        source = ast.parse((ROOT/'app/app.py').read_text(encoding='utf-8'))
        branch = next(n for n in source.body if isinstance(n, ast.If)
                      and ast.unparse(n.test) == "nav == 'Kolo'")
        st = SimpleNamespace(subheader=Mock(), warning=Mock(), error=Mock(),
                             stop=Mock(side_effect=AssertionError('Stopped')),
                             dataframe=Mock(), column_config=SimpleNamespace(TextColumn=Mock()))
        namespace = dict(st=st, pd=pd, season='2026-27',
                         H=pd.DataFrame(columns=['season','venue','team','opponent']),
                         load_fixtures=Mock(return_value=frame),
                         current_round=Mock(return_value=(6,frame)),
                         sync_officials=Mock(), referee_for_match=referee)
        exec(compile(ast.Module(body=branch.body,type_ignores=[]),'round-view','exec'),namespace)
        namespace['sync_officials'].assert_called_once_with(6)
        st.subheader.assert_called_once_with('Kolo 6')
        return st, st.dataframe.call_args.args[0]

    def fixtures(self):
        return pd.DataFrame([dict(home_team=f'Home {i}',away_team=f'Away {i}',
                                 match_date='2026-10-10',kickoff_time=f'{12+i}:00',played=False)
                             for i in range(10)])

    def test_ten_matches_sorted_no_scoring_controls(self):
        st, result = self.render(self.fixtures().iloc[::-1], lambda h,a,r:'P Tierney')
        self.assertEqual(len(result),10)
        self.assertEqual(result['Domácí'].tolist(),[f'Home {i}' for i in range(10)])
        self.assertEqual(set(result['Rozhodčí']),{'P Tierney'})
        st.warning.assert_not_called()
        # No button, scorer, archive or session_state is provided: any such call fails.

    def test_missing_referee_date_time(self):
        frame=self.fixtures()
        frame.loc[0,['match_date','kickoff_time']]=None
        _, result=self.render(frame,lambda *args:None)
        self.assertEqual(set(result['Rozhodčí']),{'Zatím neurčen'})
        self.assertEqual(result.iloc[-1]['Datum / čas'],'Termín neurčen')

    def test_partial_schedule_warns(self):
        st,result=self.render(self.fixtures().iloc[:9])
        self.assertEqual(len(result),9)
        st.warning.assert_called_once()

    def test_existing_round_selection_local_schedule(self):
        module=ast.parse((ROOT/'scripts/update_fixtures.py').read_text(encoding='utf-8'))
        func=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='current_round')
        ns={}
        exec(compile(ast.Module(body=[func],type_ignores=[]),'current-round','exec'),ns)
        schedule=pd.read_csv(ROOT/'data/fixtures/premier_league_2026-27.csv')
        history=pd.read_csv(ROOT/'data/tables/team_match_stats.csv')
        done=history[(history.season=='2026-27') & (history.venue=='H')]
        done=done.rename(columns={'team':'home_team','opponent':'away_team'})
        rnd,frame=ns['current_round'](schedule,done)
        expected=min(r for r,g in schedule.groupby('match_round')
                     if any((x.home_team,x.away_team) not in set(zip(done.home_team,done.away_team))
                            for x in g.itertuples()))
        self.assertEqual(rnd,expected)
        self.assertEqual(len(frame),10)


if __name__=='__main__':
    unittest.main()
