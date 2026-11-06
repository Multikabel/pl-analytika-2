"""Automatic UI analysis with synthetic artifacts, no production scorer calls."""
import ast
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from app import match_analysis as analysis
from app.table_layout import summary_config, SUMMARY_LEGEND
import score_round
import prediction_archive


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for folder, names in [('models', [m+'_model.joblib' for m in analysis.MARKETS]),
                              ('data/tables', ['team_match_stats.csv','referee_match_stats.csv']),
                              ('data/fixtures', ['schedule.csv'])]:
            for name in names:
                p=self.base/folder/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'fixture')
        analysis.cached_analysis.clear()
        self.addCleanup(analysis.cached_analysis.clear)
        validator=patch('app.model_loading.validate_models',return_value=[])
        validator.start(); self.addCleanup(validator.stop)
        self.scorer=Mock(return_value=pd.DataFrame({'prediction':[12.0]}))
        patcher=patch.object(score_round,'score_fixtures',self.scorer)
        patcher.start(); self.addCleanup(patcher.stop)

    def call(self, **kw):
        args=dict(home='A',away='B',match_date='2026-10-10',season='2026-27',referee='R')
        args.update(kw)
        return analysis.analyze(self.base,**args)

    def test_cache_repeat_and_all_context_inputs(self):
        self.call(); result,_=self.call()
        self.assertEqual(self.scorer.call_count,1)
        result.loc[0,'prediction']=999
        self.assertEqual(self.call()[0].iloc[0].prediction,12)
        for k,v in [('home','C'),('away','D'),('match_date','2026-10-11'),('season','2025-26'),('referee','S')]:
            self.call(**{k:v})
        self.assertEqual(self.scorer.call_count,6)

    def test_content_changes_invalidate_even_same_size(self):
        self.call()
        paths=list((self.base/'models').glob('*'))+list((self.base/'data/tables').glob('*'))+list((self.base/'data/fixtures').glob('*'))
        for p in paths:
            p.write_bytes(b'changed'); self.call()
        self.assertEqual(self.scorer.call_count,1+len(paths))

    def test_missing_model_never_scores_or_returns_old_result(self):
        self.call(); (self.base/'models/fouls_model.joblib').unlink()
        with self.assertRaises(FileNotFoundError): self.call()
        self.assertEqual(self.scorer.call_count,1)

    def test_concurrent_input_change_rejected(self):
        def change(*args):
            (self.base/'data/tables/team_match_stats.csv').write_bytes(b'new')
            return pd.DataFrame({'prediction':[1]})
        self.scorer.side_effect=change
        with self.assertRaises(ValueError): self.call()

    def test_invalid_predictions_not_cached(self):
        for value in [float('nan'), float('inf'), -1.]:
            self.scorer.return_value=pd.DataFrame({'prediction':[value]})
            with self.assertRaises(ValueError): self.call()
        self.scorer.return_value=pd.DataFrame({'prediction':[10.], 'p_over':[1.1], 'p_under':[-.1]})
        with self.assertRaises(ValueError): self.call()

    def render(self, home='A', manual=False, error=None):
        tree=ast.parse((ROOT/'app/app.py').read_text(encoding='utf-8'))
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="nav == 'Zápas'")
        clear=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='clear_match_results')
        rows=[dict(team=t,market=m,prediction=10.,line=9.5,p_over=.6,fair_over=1/.6,venue='H')
              for t in [home,'B','CELKEM'] for m in ['fouls','corners','yellow_cards','fouls_total','corners_total','yellow_cards_total']]
        scored=pd.DataFrame(rows)
        picked=scored.iloc[:1].assign(bookmaker_odds=2.,stake_units=1.)
        col=SimpleNamespace(metric=Mock(),selectbox=lambda label,options,**kw:options[0],text_input=Mock())
        if not hasattr(self,'state'): self.state=State()
        st=SimpleNamespace(session_state=self.state,subheader=Mock(),caption=Mock(),warning=Mock(),
                           spinner=lambda *a:nullcontext(),columns=lambda n:[col]*n,
                           expander=lambda *a:nullcontext(),dataframe=Mock(),success=Mock(),info=Mock(),
                           button=Mock(return_value=manual))
        ns=dict(st=st,pd=pd,np=np,BASE=self.base,TABLES=self.base/'data/tables',
                select_current_match=lambda:(home,'B','2026-10-10','2026-27','R',6),
                analyze=Mock(return_value=(scored,('v1',)),side_effect=error),
                MARKETS=analysis.MARKETS,LABEL={r['market']:r['market'] for r in rows},
                selectable_tip_table=Mock(return_value=picked),pct=lambda p:f'{p:.0%}',
                archive_selected_predictions=prediction_archive.archive_selected_predictions)
        with patch.object(prediction_archive,'LOG_PATH',self.base/'tips.csv'), patch.object(prediction_archive,'github_enabled',return_value=False):
            exec(compile(ast.Module(body=[clear,*branch.body],type_ignores=[]),'actual-match-ui','exec'),ns)
        return st,ns

    def test_automatic_first_and_changed_match_no_writes(self):
        st,ns=self.render()
        ns['analyze'].assert_called_once_with(self.base,'A','B','2026-10-10','2026-27','R')
        self.assertFalse((self.base/'tips.csv').exists())
        st,ns=self.render(home='C')
        self.assertEqual(self.state.single_identity[0],'C')
        self.assertEqual(self.state.single.iloc[0].team,'C')
        self.assertTrue(all('Spočítat' not in c.args[0] for c in st.button.call_args_list))

    def test_missing_model_clears_stale_ui(self):
        self.render()
        st,_=self.render(error=FileNotFoundError('missing model'))
        self.assertNotIn('single',self.state)
        st.warning.assert_called_once(); st.button.assert_not_called()

    def test_manual_save_only_on_explicit_click(self):
        self.render(manual=True)
        saved=pd.read_csv(self.base/'tips.csv')
        self.assertEqual(len(saved),1)
        self.assertEqual(saved.iloc[0].home_team,'A')
        self.assertEqual(saved.iloc[0].bookmaker_odds,2.)
        self.assertEqual(saved.iloc[0].status,'pending')

    def test_brand_filter_and_presentation_contract(self):
        source=(ROOT/'app/app.py').read_text(encoding='utf-8')
        self.assertIn('page_title="NABOMBI Skaut"',source)
        self.assertIn('st.title("⚽ NABOMBI Skaut")',source)
        for removed in ['min_fair','best_high_odds_lines','Spočítat zápas','snapshot_model_predictions']:
            self.assertNotIn(removed,source)
        st=SimpleNamespace(column_config=SimpleNamespace(NumberColumn=lambda label,**kw:dict(label=label,**kw)))
        cfg=summary_config(st)
        self.assertEqual([v['label'] for v in cfg.values()],['#','Z','N','Σ','Ø','Min','Max'])
        self.assertEqual(cfg['Průměr']['format'],'%.1f')
        self.assertEqual(cfg['Zápasy']['format'],'%d')
        self.assertLessEqual(max(v['width'] for v in cfg.values()),52)
        self.assertIn('N = platná pozorování',SUMMARY_LEGEND)


if __name__=='__main__': unittest.main()
