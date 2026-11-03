"""Navigation contract without running production scoring or archive writes."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

APP=Path(__file__).resolve().parents[1]/'app/app.py'


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.tree=ast.parse(APP.read_text(encoding='utf-8'))

    def test_exact_menu(self):
        nav=next(n for n in self.tree.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='nav' for t in n.targets))
        self.assertEqual(ast.literal_eval(nav.value.args[1]),
                         ['Kolo','Zápas','Cross-TAB','Rozhodčí','Týmy'])

    def test_no_removed_page_routes(self):
        routes=[n.test for n in ast.walk(self.tree) if isinstance(n,ast.If)
                and any(isinstance(x,ast.Name) and x.id=='nav' for x in ast.walk(n.test))]
        values={x.value for r in routes for x in ast.walk(r) if isinstance(x,ast.Constant)}
        self.assertFalse({'Tipy','Statistiky','Data'} & values)
        self.assertTrue({'Kolo','Zápas','Cross-TAB','Rozhodčí','Týmy'} <= values)

    def test_match_retains_selection_scoring_and_save(self):
        match=next(n for n in ast.walk(self.tree) if isinstance(n,ast.If)
                   and ast.unparse(n.test)=="nav == 'Zápas'")
        calls={n.func.id for statement in match.body for n in ast.walk(statement)
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertTrue({'select_current_match','predict_one','snapshot_model_predictions',
                         'archive_selected_predictions','selectable_tip_table'} <= calls)

    def test_scoring_wrapper_preserves_inputs(self):
        func=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='predict_one')
        scorer=Mock(return_value='result'); ns={'score_fixtures':scorer}
        exec(compile(ast.Module(body=[func],type_ignores=[]),'scoring-wrapper','exec'),ns)
        self.assertEqual(ns['predict_one']('A','B','2026-11-03','2026-27','R'),'result')
        scorer.assert_called_once_with([dict(home_team='A',away_team='B',match_date='2026-11-03',
                                            season='2026-27',referee='R')])


if __name__=='__main__':
    unittest.main()
