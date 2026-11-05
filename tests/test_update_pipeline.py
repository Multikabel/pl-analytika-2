import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import pandas as pd
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import auto_update
import update_data as importer

class OrchestrationTests(unittest.TestCase):
    def test_officials_failure_deferred_past_settlements_and_preservation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            calls=[]
            def run(args,required=True):
                calls.append(args[1])
                return 1 if args[1]=='scripts/update_officials.py' else 0
            with patch.object(auto_update,'run',side_effect=run), patch.object(auto_update,'validate_current_state'), patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}):
                with self.assertRaises(SystemExit) as exc:
                    auto_update.main()
            self.assertEqual(1,exc.exception.code)
            self.assertLess(calls.index('scripts/prediction_archive.py'),calls.index('scripts/update_officials.py'))
            self.assertLess(calls.index('scripts/model_prediction_stats.py'),calls.index('scripts/update_officials.py'))
            self.assertNotIn('scripts/snapshot_model_predictions.py',calls)
            self.assertEqual('data_completed=true\n',output.read_text())

    def test_critical_failure_does_not_signal_publishable_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            with patch.object(auto_update,'run',side_effect=SystemExit(2)), patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}):
                with self.assertRaises(SystemExit):auto_update.main()
            self.assertFalse(output.exists())



class FailureTests(unittest.TestCase):
    def test_snapshot_failure_does_not_signal_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            def run(args,required=True):
                if args[1]=='scripts/snapshot_model_predictions.py': raise SystemExit(3)
                return 0
            with patch.object(auto_update,'run',side_effect=run), patch.object(auto_update,'validate_current_state'), patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}):
                with self.assertRaises(SystemExit):auto_update.main()
            self.assertFalse(output.exists())

    def test_download_503_and_stale_fallback_preserve_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); target=root/'2026-27.csv'
            target.write_text('FTHG,FTAG\n1,0\n2,1\n')
            before=target.read_bytes()
            with patch.object(importer,'RAW',root), patch.object(importer.requests,'get',side_effect=requests.HTTPError('503')), patch.object(importer.time,'sleep'), patch.object(importer,'_fallback_fpl_core',return_value=(b'stale',1)):
                self.assertFalse(importer.download_current('2627','2026-27.csv'))
            self.assertEqual(before,target.read_bytes())

    def test_empty_html_and_missing_columns_rejected(self):
        for raw in (b'',b'<html>503</html>',b'HomeTeam,AwayTeam\nA,B\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                importer._validate_current_csv_bytes(raw,'mock')

    def test_conflicting_duplicate_results_leave_import_unchanged(self):
        from test_sqlite_import import SQLiteImportTests, played
        case=SQLiteImportTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        case.source([played()]);case.run_import();before=case.state()
        case.source([played(),played(FTHG=5)])
        with self.assertRaisesRegex(ValueError,'ambiguous fixture'):
            case.run_import()
        self.assertEqual(before,case.state())
