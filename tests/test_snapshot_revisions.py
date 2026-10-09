"""Synthetic revision lifecycle, no real models, data writes or network."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_prediction_stats as stats
import model_snapshot_revisions as ledger
import revise_model_snapshot as runner


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "model_prediction_log.csv"
        self.models = self.root / "models"
        self.models.mkdir()
        self.data = self.root / "features.csv"
        pd.DataFrame([dict(match_date="2026-09-20")]).to_csv(self.data, index=False)
        self.schedule = pd.DataFrame([dict(season="2026-27", match_round=6,
            home_team=f"H{i}", away_team=f"A{i}", match_date="2026-10-10",
            kickoff_utc="2026-10-10T11:30:00+00:00") for i in range(10)])
        self.officials = self.schedule[["home_team", "away_team"]].copy()
        self.officials["referee"] = "Paul Tierney"
        records = []
        for fixture in self.schedule.itertuples():
            for team, venue in ((fixture.home_team, "H"), (fixture.away_team, "A"), ("CELKEM", "T")):
                for base in ("fouls", "corners", "yellow_cards"):
                    row = dict.fromkeys(stats.COLUMNS, "")
                    row.update(season="2026-27", match_round=6, home_team=fixture.home_team,
                        away_team=fixture.away_team, match_date=fixture.match_date,
                        team=team, venue=venue, market=base + ("_total" if venue == "T" else ""),
                        created_at="2026-09-22T00:50:34", status="pending", prediction=4.,
                        test_line=3.5, range_low=3., range_high=5., range_probability=.5,
                        model_version="count-models-v1.4")
                    row["model_prediction_id"] = stats._id(row)
                    records.append(row)
        self.old = pd.DataFrame(records)
        historical = self.old.iloc[:1].copy()
        historical["home_team"] = "Historical"
        historical["team"] = "Historical"
        historical["match_round"] = 4
        historical["status"] = "settled"
        historical["model_prediction_id"] = historical.apply(stats._id, axis=1)
        self.base = pd.concat([historical, self.old], ignore_index=True)
        self.base.to_csv(self.archive, index=False)
        self.before = self.archive.read_bytes()
        self.enterContext(patch.object(stats, "LOG_PATH", self.archive))
        self.enterContext(patch.object(ledger.github, "enabled", return_value=False))
        self.enterContext(patch.object(stats, "github_enabled", return_value=False))
        self.enterContext(patch.object(runner, "DATA_PATH", self.data))
        self.enterContext(patch.object(runner, "LOCK_PATH", self.root / "guard.sqlite"))
        self.enterContext(patch.object(runner, "MODELS_DIR", self.models))
        self.clock = self.enterContext(patch.object(runner, "utc_now", return_value=
            datetime(2026, 10, 9, 23, tzinfo=timezone.utc)))
        self.context = self.enterContext(patch.object(runner, "live_context",
            side_effect=lambda *args: (self.schedule, self.officials)))
        self.train = self.enterContext(patch.object(runner.training, "main", side_effect=self.train_fake))
        scored = self.old.copy()
        scored["prediction"] = 6.
        scored["referee"] = "P Tierney"
        scored["line"] = 3.5
        self.score = self.enterContext(patch.object(runner.score_round, "score_fixtures", return_value=scored))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("No network")))

    def train_fake(self):
        for m in runner.training.MARKETS:
            (self.models / f"{m}_model.joblib").write_bytes(b"synthetic test artifact")
            (self.models / f"{m}_model_metadata.json").write_text(json.dumps(
                dict(trained_at="2026-10-09T23:00:00", trained_rows=10)))

    def test_original_bytes_and_other_round_preserved(self):
        new, created = runner.create()
        self.assertTrue(created)
        self.assertEqual(len(new), 90)
        self.assertEqual(self.archive.read_bytes(), self.before)
        self.assertEqual(new.groupby(["home_team", "away_team"]).referee.nunique().tolist(), [1] * 10)
        active = stats.load_log()
        self.assertEqual(len(active[active.match_round.eq(6)]), 90)
        self.assertTrue(active[active.match_round.eq(6)].status.eq("pending").all())
        self.assertEqual(active[active.match_round.eq(4)].iloc[0].prediction, 4.)

    def test_second_run_no_training_scoring_or_revision_three(self):
        runner.create()
        before = ledger.path_for(self.archive).read_bytes()
        _, created = runner.create()
        self.assertFalse(created)
        self.assertEqual(ledger.path_for(self.archive).read_bytes(), before)
        self.train.assert_called_once()
        self.score.assert_called_once()

    def test_missing_official(self):
        self.officials = self.officials.iloc[:-1]
        with self.assertRaisesRegex(ValueError, "Officials"):
            runner.create()
        self.train.assert_not_called()
        self.assertFalse(ledger.path_for(self.archive).exists())
        self.assertEqual(self.archive.read_bytes(), self.before)

    def test_duplicate_official(self):
        self.officials.iloc[9] = self.officials.iloc[0]
        with self.assertRaisesRegex(ValueError, "Officials"):
            runner.create()
        self.train.assert_not_called()

    def test_after_kickoff(self):
        self.clock.return_value = datetime(2026, 10, 10, 11, 30, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "kickoff"):
            runner.create()
        self.train.assert_not_called()
        self.assertFalse(ledger.path_for(self.archive).exists())

    def test_unknown_kickoff(self):
        self.schedule.loc[0, "kickoff_utc"] = None
        with self.assertRaisesRegex(ValueError, "kickoff"):
            runner.create()
        self.train.assert_not_called()

    def test_officials_changed_while_scoring(self):
        changed = self.officials.copy()
        changed.loc[0, "referee"] = "Michael Oliver"
        self.context.side_effect = [(self.schedule, self.officials), (self.schedule, changed)]
        with self.assertRaisesRegex(ValueError, "changed during scoring"):
            runner.create()
        self.assertFalse(ledger.path_for(self.archive).exists())

    def test_settlement_and_summary_only_active_revision(self):
        runner.create()
        team_rows = []
        for fx in self.schedule.itertuples():
            for team, opponent, venue in ((fx.home_team, fx.away_team, "H"), (fx.away_team, fx.home_team, "A")):
                team_rows.append(dict(season="2026-27", match_id=fx.home_team, team=team,
                    opponent=opponent, venue=venue, match_date=fx.match_date,
                    fouls_committed=8, corners_for=8, yellow_cards=8))
        table = self.root / "teams.csv"
        pd.DataFrame(team_rows).to_csv(table, index=False)
        with patch.object(stats, "TEAM_MATCH_PATH", table):
            self.assertEqual(stats.settle()["settled"], 90)
            self.assertEqual(stats.settle()["settled"], 0)
        self.assertEqual(self.archive.read_bytes(), self.before)
        active = stats.load_log()
        mw6 = active[active.match_round.eq(6)]
        self.assertEqual(stats.summary(mw6)["n"], 90)
        self.assertTrue(mw6.prediction.eq(6).all())
        self.assertEqual(len(pd.read_csv(ledger.path_for(self.archive))), 90)

    def test_immutable_settlement_conflict(self):
        new, _ = runner.create()
        candidate = stats.load_log()
        candidate.loc[candidate.match_round.eq(6), "prediction"] = 100
        before = ledger.path_for(self.archive).read_bytes()
        with self.assertRaisesRegex(ValueError, "Immutable"):
            stats._save_log(candidate, "test")
        self.assertEqual(ledger.path_for(self.archive).read_bytes(), before)
        self.assertEqual(self.archive.read_bytes(), self.before)

    def test_partial_revision_rejected(self):
        new, _ = runner.create()
        with self.assertRaisesRegex(ValueError, "ninety|90"):
            ledger.active(self.base, new.iloc[:-1])

    def test_sha_retry_revalidates_immutable_prediction(self):
        new, _ = runner.create()
        candidate = new.copy()
        candidate["status"] = "settled"
        changed_remote = new.copy()
        changed_remote.loc[0, "prediction"] = 100
        before = ledger.path_for(self.archive).read_bytes()
        with patch.object(ledger.github, "enabled", return_value=True), \
             patch.object(ledger.github, "read_csv", side_effect=[(new, "old"), (changed_remote, "new")]), \
             patch.object(ledger.github, "write_csv", return_value=(False, "SHA conflict")) as write:
            with self.assertRaisesRegex(ValueError, "Immutable"):
                ledger.save_settlement(self.archive, new, candidate)
        self.assertEqual(write.call_count, 1)
        self.assertEqual(ledger.path_for(self.archive).read_bytes(), before)
        self.assertEqual(self.archive.read_bytes(), self.before)

    def test_no_settled_rollback_and_explicit_conflict(self):
        new, _ = runner.create()
        settled = new.copy()
        settled["status"] = "settled"
        settled["actual_value"] = 8
        self.assertTrue(ledger.merge_settlement(settled, new).status.eq("settled").all())
        conflict = settled.copy()
        conflict.loc[0, "actual_value"] = 9
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            ledger.merge_settlement(settled, conflict)

    def test_first_kickoff_reached_during_scoring(self):
        def score(*args):
            self.clock.return_value = datetime(2026, 10, 10, 11, 30, tzinfo=timezone.utc)
            return self.old.assign(line=3.5, referee="P Tierney")
        self.score.side_effect = score
        with self.assertRaisesRegex(ValueError, "kickoff"):
            runner.create()
        self.assertFalse(ledger.path_for(self.archive).exists())
        self.assertEqual(self.archive.read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
