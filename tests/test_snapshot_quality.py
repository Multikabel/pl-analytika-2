"""Exercise the real snapshot entry point with isolated inputs and scoring spies."""
import contextlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import snapshot_model_predictions as runner


class SnapshotQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = self.base / "model_prediction_log.csv"
        pd.DataFrame([dict(season="2026-27", venue="H", team="Old", opponent="Other")]).to_csv(
            self.base / "team_match_stats.csv", index=False)
        self.schedule = pd.DataFrame([dict(season="2026-27", match_round=6,
            home_team=f"Home{i}", away_team=f"Away{i}", match_date="2026-09-26",
            kickoff_time="15:00") for i in range(10)])
        self.officials = self.schedule[["season", "match_round", "home_team", "away_team"]].copy()
        self.officials["referee"] = "Michael Oliver"
        self.enterContext(patch.object(runner, "TABLES", self.base))
        self.enterContext(patch.object(runner, "LOG_PATH", self.archive))
        self.load = self.enterContext(patch.object(runner, "load_fixtures", return_value=self.schedule))
        self.sync = self.enterContext(patch.object(runner, "sync_officials", return_value=self.officials))
        self.score = self.enterContext(patch.object(runner, "score_fixtures", return_value=pd.DataFrame()))
        self.save = self.enterContext(patch.object(runner, "snapshot", return_value=90))
        self.clock = self.enterContext(patch.object(runner, "utc_now", return_value=
            datetime(2026, 9, 26, 13, 59, tzinfo=timezone.utc)))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))

    def run_main(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runner.main()
        return output.getvalue()

    def assert_skipped(self, reason):
        self.assertIn(reason, self.run_main())
        self.score.assert_not_called()
        self.save.assert_not_called()
        self.assertFalse(self.archive.exists())

    def test_zero_officials(self):
        self.sync.return_value = self.officials.iloc[:0]
        self.assert_skipped("officials incomplete (0/10)")

    def test_nine_officials(self):
        self.sync.return_value = self.officials.iloc[:9]
        self.assert_skipped("officials incomplete (9/10)")

    def test_ten_matching_officials(self):
        self.run_main()
        fixtures = self.score.call_args.args[0]
        self.assertEqual(len(fixtures), 10)
        self.assertEqual({(f["home_team"], f["away_team"]) for f in fixtures},
                         set(zip(self.schedule.home_team, self.schedule.away_team)))
        self.assertTrue(all(f["referee"] == "M Oliver" for f in fixtures))
        self.save.assert_called_once_with(self.score.return_value, 6)

    def test_wrong_fixture_among_ten(self):
        self.officials.loc[9, "away_team"] = "Wrong"
        self.assert_skipped("officials incomplete (9/10)")

    def test_duplicate_appointment(self):
        self.sync.return_value = pd.concat([self.officials, self.officials.iloc[:1]])
        self.assert_skipped("officials incomplete (9/10)")

    def test_invalid_names(self):
        for name in ["", None, "TBD", "Default Referee", "123 456"]:
            with self.subTest(name=name):
                self.officials.loc[0, "referee"] = name
                self.assert_skipped("officials incomplete (9/10)")

    def test_wrong_round(self):
        self.officials["match_round"] = 5
        self.assert_skipped("officials incomplete (0/10)")

    def test_wrong_season(self):
        self.officials["season"] = "2025-26"
        self.assert_skipped("officials incomplete (0/10)")

    def test_first_kickoff_reached_in_uk_summer_time(self):
        self.clock.return_value = datetime(2026, 9, 26, 14, tzinfo=timezone.utc)
        self.assert_skipped("first kickoff reached")
        self.sync.assert_not_called()

    def test_missing_kickoff(self):
        self.schedule.loc[0, "kickoff_time"] = ""
        self.assert_skipped("kickoff cannot be verified")

    def test_not_ten_expected_fixtures(self):
        self.load.return_value = self.schedule.iloc[:9]
        self.assert_skipped("invalid expected fixture identities")

    def test_duplicate_expected_fixture(self):
        self.schedule.loc[9] = self.schedule.iloc[0]
        self.assert_skipped("invalid expected fixture identities")

    def test_existing_snapshot_is_untouched(self):
        rows = []
        for r in self.schedule.itertuples():
            for market in ["fouls", "corners", "yellow_cards"]:
                for team in [r.home_team, r.away_team, "CELKEM"]:
                    rows.append(dict(season=r.season, match_round=6, home_team=r.home_team,
                        away_team=r.away_team, team=team, referee="M Oliver",
                        market=market if team != "CELKEM" else market + "_total",
                        prediction=4.2, range_low=3, range_high=5))
        pd.DataFrame(rows).to_csv(self.archive, index=False)
        before = self.archive.read_bytes()
        for _ in range(2):
            self.assertIn("preserving original snapshot", self.run_main())
        self.assertEqual(before, self.archive.read_bytes())
        self.score.assert_not_called()
        self.save.assert_not_called()
        self.sync.assert_not_called()

    def test_sync_exception_returns_normally(self):
        self.sync.side_effect = RuntimeError("offline")
        self.assert_skipped("officials synchronization failed: offline")

    def test_deadline_during_sync(self):
        self.clock.side_effect = [datetime(2026, 9, 26, 13, 59, tzinfo=timezone.utc),
                                  datetime(2026, 9, 26, 14, tzinfo=timezone.utc)]
        self.assert_skipped("first kickoff reached during officials synchronization")

    def test_deadline_during_scoring(self):
        before = datetime(2026, 9, 26, 13, 59, tzinfo=timezone.utc)
        self.clock.side_effect = [before, before, datetime(2026, 9, 26, 14, tzinfo=timezone.utc)]
        self.assertIn("first kickoff reached during scoring", self.run_main())
        self.score.assert_called_once()
        self.save.assert_not_called()

    def test_mw5_metadata_is_explicitly_retrospective(self):
        path = Path(__file__).resolve().parents[1] / "data/predictions/snapshot_quality_audits.json"
        audit = json.loads(path.read_text(encoding="utf-8"))["audits"][0]
        self.assertEqual((audit["season"], audit["match_round"]), ("2026-27", 5))
        self.assertEqual(audit["metadata_origin"], "retrospective_audit")
        self.assertEqual(audit["snapshot_quality"], "incomplete_officials")
        self.assertIs(audit["officials_complete"], False)
        self.assertEqual((audit["officials_present"], audit["officials_expected"]), (0, 10))
        self.assertEqual(len(set(audit["model_prediction_ids"])), 90)


if __name__ == "__main__":
    unittest.main()
