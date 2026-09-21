"""Synthetic regression tests; no production files or GitHub calls are used.

Run: python -B -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prediction_archive as tips
import model_prediction_stats as models
import github_persistence as persistence


def match(mid, home, away, date, home_value, away_value):
    return [dict(match_id=mid, season="2026-27", match_date=date,
                 team=team, opponent=opponent, venue=venue,
                 fouls_committed=value, corners_for=value, yellow_cards=value)
            for team, opponent, venue, value in
            [(home, away, "H", home_value), (away, home, "A", away_value)]]


FIRST = match("AB", "A", "B", "2026-08-01", 4, 6)
RETURN = match("BA", "B", "A", "2027-01-01", 2, 12)


def prediction(module=tips, market="fouls", team="A", home="A", away="B"):
    row = dict.fromkeys(module.COLUMNS)
    row.update(created_at="2026-07-01T12:00:00", season="2026-27",
               match_round=1, match_date="2026-07-31", home_team=home,
               away_team=away, referee="R Test", team=team,
               venue="T" if team == "CELKEM" else ("H" if team == home else "A"),
               market=market, prediction=4., line=15.5 if team == "CELKEM" else 8.5,
               p_over=.5, fair_over=2., bookmaker_odds=2., stake_units=1.,
               model_version="synthetic", selection_source="manual", status="pending",
               test_line=3.5, range_low=3., range_high=5., range_probability=.5)
    if module is tips:
        row["prediction_id"] = tips._prediction_id(row)
    else:
        row["model_prediction_id"] = models._id(row)
    return pd.DataFrame([row], columns=module.COLUMNS)


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch("requests.sessions.Session.request",
                                side_effect=AssertionError("Network forbidden")))

    def settle(self, module, rows, log):
        table, archive = self.root / "teams.csv", self.root / "archive.csv"
        pd.DataFrame(rows).to_csv(table, index=False)
        log.to_csv(archive, index=False)
        with patch.object(module, "TEAM_MATCH_PATH", table), \
             patch.object(module, "LOG_PATH", archive), \
             patch.object(module, "github_enabled", return_value=False):
            if module is tips:
                module.settle_predictions()
            else:
                module.settle()
        return pd.read_csv(archive)

    def test_both_legs_in_either_csv_order(self):
        for module in (tips, models):
            for base in ("fouls", "corners", "yellow_cards"):
                for team, expected in (("A", 4.), ("B", 6.), ("CELKEM", 10.)):
                    market = base + ("_total" if team == "CELKEM" else "")
                    for rows in (FIRST + RETURN, RETURN + FIRST):
                        with self.subTest(module=module.__name__, market=market, team=team,
                                          first_id=rows[0]["match_id"]):
                            log = prediction(module, market, team)
                            out = self.settle(module, rows, log).iloc[0]
                            self.assertEqual(out.status, "settled")
                            self.assertEqual(out.actual_value, expected)
                            self.assertEqual(out.match_date, "2026-08-01")
                            if module is tips:
                                self.assertEqual(out.result, "LOSS")
                                self.assertEqual(out.profit_units, -1.)
                            else:
                                for col in ("model_prediction_id", "prediction", "test_line",
                                            "range_low", "range_high", "range_probability"):
                                    self.assertEqual(out[col], log.iloc[0][col])
                                self.assertEqual(out.error, expected - 4.)

    def test_reverse_fixture_alone_cannot_settle_future_match(self):
        for module in (tips, models):
            for market, team in (("fouls", "A"), ("fouls_total", "CELKEM")):
                with self.subTest(module=module.__name__, market=market):
                    log = prediction(module, market, team, home="B", away="A")
                    out = self.settle(module, FIRST, log).iloc[0]
                    self.assertEqual(out.status, "pending")
                    self.assertTrue(pd.isna(out.actual_value))
                    self.assertEqual(out.match_date, log.iloc[0].match_date)

    def test_missing_duplicate_or_inconsistent_rows_remain_pending(self):
        variants = {
            "duplicate_home": FIRST + [FIRST[0]],
            "different_id_same_fixture": FIRST + match("AB2", "A", "B", "2026-08-02", 4, 6),
            "missing_away": FIRST[:1],
            "duplicate_away": FIRST + [FIRST[1]],
            "wrong_away_team": [FIRST[0], dict(FIRST[1], team="C")],
            "wrong_away_venue": [FIRST[0], dict(FIRST[1], venue="H")],
            "wrong_away_season": [FIRST[0], dict(FIRST[1], season="2025-26")],
            "missing_match_id": [dict(r, match_id=None) for r in FIRST],
        }
        for module in (tips, models):
            for name, rows in variants.items():
                for market, team in (("fouls", "B"), ("fouls_total", "CELKEM")):
                    with self.subTest(module=module.__name__, variant=name, market=market):
                        log = prediction(module, market, team)
                        out = self.settle(module, rows, log).iloc[0]
                        self.assertEqual(out.status, "pending")
                        self.assertEqual(out.match_date, log.iloc[0].match_date)

    def test_missing_actual_remains_pending(self):
        rows = [FIRST[0], dict(FIRST[1], fouls_committed=None)]
        for module in (tips, models):
            for market, team in (("fouls", "B"), ("fouls_total", "CELKEM")):
                with self.subTest(module=module.__name__, market=market):
                    out = self.settle(module, rows, prediction(module, market, team)).iloc[0]
                    self.assertEqual(out.status, "pending")

    def test_settled_rows_are_not_recomputed(self):
        for module in (tips, models):
            log = prediction(module)
            log.loc[0, ["status", "actual_value"]] = ["settled", 99.]
            out = self.settle(module, FIRST, log).iloc[0]
            self.assertEqual(out.actual_value, 99.)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tips.csv"
        self.enterContext(patch.object(tips, "LOG_PATH", self.path))
        self.enterContext(patch.object(tips, "github_enabled", return_value=True))
        self.enterContext(patch("requests.sessions.Session.request",
                                side_effect=AssertionError("Network forbidden")))
        self.pending = prediction()
        self.settled = self.pending.copy()
        self.settled.loc[0, ["status", "actual_value", "result", "profit_units",
                             "settled_at", "match_date"]] = [
            "settled", 4., "LOSS", -1., "2026-08-02T00:00:00", "2026-08-01"]

    def save(self, remote, candidate, settlement=True, retry_remote=None):
        reads = [(remote.copy(), "sha-1")]
        writes = [(True, {})]
        if retry_remote is not None:
            reads.append((retry_remote.copy(), "sha-2"))
            writes = [(False, "conflict"), (True, {})]
        with patch.object(tips, "github_read_csv", side_effect=reads), \
             patch.object(tips, "github_write_csv", side_effect=writes) as write:
            if settlement:
                tips._save_log(candidate.copy(), settlement=True)
            else:
                tips._save_log(candidate.copy())
        return write

    def test_pending_to_settled_preserves_original_prediction_fields(self):
        local = self.settled.copy()
        for col in ("prediction", "p_over", "fair_over"):
            local.loc[0, col] = 123.
        write = self.save(self.pending, local)
        sent = write.call_args.args[1].iloc[0]
        settlement_fields = {"status", "actual_value", "result", "profit_units", "settled_at", "match_date"}
        for col in tips.COLUMNS:
            expected = self.settled.iloc[0][col] if col in settlement_fields else self.pending.iloc[0][col]
            self.assertTrue(pd.isna(sent[col]) and pd.isna(expected) or sent[col] == expected, col)
        self.assertEqual(pd.read_csv(self.path).iloc[0].status, "settled")

    def test_unsynchronized_pending_tip_preserves_local_file_and_remote(self):
        new = self.pending.copy()
        new.loc[0, "prediction_id"] = "unsynchronized-B"
        local = pd.concat([self.settled, new], ignore_index=True)
        for disk_only in (False, True):
            for retry in (False, True):
                with self.subTest(disk_only=disk_only, retry=retry):
                    local.to_csv(self.path, index=False)
                    before = self.path.read_bytes()
                    candidate = self.settled if disk_only else local
                    remote = self.pending.copy()
                    remote_before = remote.copy(deep=True)
                    reads = [(remote, "sha")]
                    if retry:
                        # B existed on the first read but disappeared before retry.
                        reads = [(pd.concat([remote, new], ignore_index=True), "old"),
                                 (remote, "new")]
                    writes = [(False, "SHA conflict"), (True, {})] if retry else [(True, {})]
                    with patch.object(tips, "github_read_csv", side_effect=reads), \
                         patch.object(tips, "github_write_csv", side_effect=writes) as write:
                        with self.assertRaisesRegex(persistence.SettlementConflictError, "unsynchronized-B"):
                            tips._save_log(candidate.copy(), settlement=True)
                        self.assertEqual(write.call_count, 1 if retry else 0)
                    self.assertEqual(self.path.read_bytes(), before)
                    pd.testing.assert_frame_equal(remote, remote_before)

    def test_changed_settlement_inputs_are_conflicts_including_retry(self):
        changes = {"season": "2025-26", "home_team": "C", "away_team": "D",
                   "team": "B", "venue": "A", "market": "corners", "line": 9.5,
                   "bookmaker_odds": 3., "stake_units": 2.}
        for field, value in changes.items():
            for retry in (False, True):
                with self.subTest(field=field, retry=retry):
                    self.pending.to_csv(self.path, index=False)
                    before = self.path.read_bytes()
                    remote = self.pending.copy()
                    remote.loc[0, field] = value
                    reads = [(remote, "sha")]
                    if retry:
                        reads = [(self.pending.copy(), "old"), (remote, "new")]
                    writes = [(False, "SHA conflict"), (True, {})] if retry else [(True, {})]
                    with patch.object(tips, "github_read_csv", side_effect=reads), \
                         patch.object(tips, "github_write_csv", side_effect=writes) as write:
                        with self.assertRaisesRegex(persistence.SettlementConflictError, field):
                            tips._save_log(self.settled.copy(), settlement=True)
                        self.assertEqual(write.call_count, 1 if retry else 0)
                    self.assertEqual(self.path.read_bytes(), before)

    def test_numeric_representations_do_not_conflict(self):
        for retry in (False, True):
            with self.subTest(retry=retry):
                local = self.settled.astype(object)
                local.loc[0, "line"] = "8.5000"
                local.loc[0, "bookmaker_odds"] = "2.0000000000000004"
                local.loc[0, "stake_units"] = "1.0"
                write = self.save(self.pending, local,
                                  retry_remote=self.pending if retry else None)
                sent = write.call_args.args[1].iloc[0]
                for field in ("line", "bookmaker_odds", "stake_units"):
                    self.assertEqual(sent[field], self.pending.iloc[0][field])

    def test_real_numeric_differences_and_invalid_values_are_conflicts(self):
        for field in ("line", "bookmaker_odds", "stake_units"):
            for value in (float(self.pending.iloc[0][field]) + 1e-9, None, "invalid", float("inf")):
                with self.subTest(field=field, value=value):
                    local = self.settled.astype(object)
                    local.loc[0, field] = value
                    with patch.object(tips, "github_read_csv", return_value=(self.pending, "sha")), \
                         patch.object(tips, "github_write_csv", return_value=(True, {})) as write:
                        with self.assertRaisesRegex(persistence.SettlementConflictError, field):
                            tips._save_log(local, settlement=True)
                        write.assert_not_called()

    def test_profit_from_different_odds_is_not_persisted(self):
        table = Path(self.temp.name) / "teams.csv"
        pd.DataFrame(match("AB", "A", "B", "2026-08-01", 12, 6)).to_csv(table, index=False)
        local = self.pending.copy()
        local.loc[0, "bookmaker_odds"] = 3.
        local.to_csv(self.path, index=False)
        before = self.path.read_bytes()
        with patch.object(tips, "TEAM_MATCH_PATH", table), \
             patch.object(tips, "load_log", return_value=local.copy()), \
             patch.object(tips, "github_read_csv", return_value=(self.pending, "sha")), \
             patch.object(tips, "github_write_csv", return_value=(True, {})) as write:
            with self.assertRaisesRegex(persistence.SettlementConflictError, "bookmaker_odds"):
                tips.settle_predictions()
            write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_retry_uses_settlement_merge(self):
        write = self.save(self.pending, self.settled, retry_remote=self.pending)
        self.assertEqual(write.call_count, 2)
        for call in write.call_args_list:
            self.assertEqual(call.args[1].iloc[0].status, "settled")
        self.assertEqual(write.call_args.kwargs["sha"], "sha-2")

    def test_successful_settlement_is_visible_on_next_remote_load(self):
        remote = self.pending.copy()

        def read(*args, **kwargs):
            return remote.copy(), "sha"

        def write(path, frame, message, sha=None):
            nonlocal remote
            remote = frame.copy()
            return True, {}

        with patch.object(tips, "github_read_csv", side_effect=read), \
             patch.object(tips, "github_write_csv", side_effect=write):
            tips._save_log(self.settled.copy(), settlement=True)
            out = tips.load_log().iloc[0]
            self.assertEqual(out.status, "settled")
            self.assertEqual(out.result, "LOSS")
            self.assertEqual(out.profit_units, -1.)

    def test_remote_settled_cannot_be_reverted(self):
        write = self.save(self.settled, self.pending)
        self.assertEqual(write.call_args.args[1].iloc[0].status, "settled")

    def test_disk_settlement_cannot_be_lost_when_only_b_can_settle(self):
        b = prediction(home="C", away="D", team="C")
        remote = pd.concat([self.pending, b], ignore_index=True)
        local = pd.concat([self.settled, b], ignore_index=True)
        local.to_csv(self.path, index=False)
        before = self.path.read_bytes()
        table = Path(self.temp.name) / "teams.csv"
        pd.DataFrame(match("CD", "C", "D", "2026-08-01", 4, 6)).to_csv(table, index=False)
        remote_before = remote.copy(deep=True)

        def write(path, frame, message, sha=None):
            nonlocal remote
            remote = frame.copy()
            return True, {}

        with patch.object(tips, "TEAM_MATCH_PATH", table), \
             patch.object(tips, "github_read_csv", side_effect=lambda *a: (remote.copy(), "sha")), \
             patch.object(tips, "github_write_csv", side_effect=write) as save:
            with self.assertRaises(persistence.SettlementConflictError):
                tips.settle_predictions()
            save.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        pd.testing.assert_frame_equal(remote, remote_before)

    def test_identical_disk_settlement_is_allowed_including_retry(self):
        for retry in (False, True):
            with self.subTest(retry=retry):
                self.settled.to_csv(self.path, index=False)
                write = self.save(self.settled, self.pending,
                                  retry_remote=self.settled if retry else None)
                self.assertEqual(write.call_count, 2 if retry else 1)
                self.assertEqual(pd.read_csv(self.path).iloc[0].status, "settled")

    def test_disk_settlement_conflicts_before_write_including_retry(self):
        for field, value in (("status", "pending"), ("actual_value", 12.),
                             ("result", "WIN"), ("profit_units", 1.),
                             ("settled_at", "2026-08-03T00:00:00"),
                             ("match_date", "2026-08-03")):
            for retry in (False, True):
                with self.subTest(field=field, retry=retry):
                    self.settled.to_csv(self.path, index=False)
                    before = self.path.read_bytes()
                    remote = self.settled.copy()
                    remote.loc[0, field] = value
                    remote_before = remote.copy(deep=True)
                    reads = [(remote, "sha")]
                    if retry:
                        reads = [(self.settled.copy(), "old"), (remote, "new")]
                    writes = [(False, "SHA conflict"), (True, {})] if retry else [(True, {})]
                    with patch.object(tips, "github_read_csv", side_effect=reads), \
                         patch.object(tips, "github_write_csv", side_effect=writes) as write:
                        with self.assertRaises(persistence.SettlementConflictError):
                            tips._save_log(self.pending.copy(), settlement=True)
                        self.assertEqual(write.call_count, 1 if retry else 0)
                    self.assertEqual(self.path.read_bytes(), before)
                    pd.testing.assert_frame_equal(remote, remote_before)

    def test_identical_settled_versions_are_allowed(self):
        self.save(self.settled, self.settled)

    def test_conflicting_settled_versions_raise_before_writing(self):
        for col, value in (("actual_value", 12.), ("result", "WIN"),
                           ("profit_units", 1.), ("settled_at", "2026-08-03T00:00:00")):
            with self.subTest(col=col):
                remote = self.settled.copy()
                remote.loc[0, col] = value
                with patch.object(tips, "github_read_csv", return_value=(remote, "sha")), \
                     patch.object(tips, "github_write_csv") as write:
                    with self.assertRaisesRegex(RuntimeError, "[Cc]onflict"):
                        tips._save_log(self.settled.copy(), settlement=True)
                    write.assert_not_called()
                    self.assertFalse(self.path.exists())

    def test_conflicting_settlement_on_retry_is_not_overwritten(self):
        remote = self.settled.copy()
        remote.loc[0, "actual_value"] = 12.
        with patch.object(tips, "github_read_csv", side_effect=[(self.pending, "1"), (remote, "2")]), \
             patch.object(tips, "github_write_csv", return_value=(False, "conflict")) as write:
            with self.assertRaisesRegex(RuntimeError, "[Cc]onflict"):
                tips._save_log(self.settled.copy(), settlement=True)
            self.assertEqual(write.call_count, 1)
            self.assertFalse(self.path.exists())

    def test_creation_remains_append_only(self):
        new = self.pending.copy()
        new.loc[0, "prediction_id"] = "new-id"
        candidate = pd.concat([self.settled, new], ignore_index=True)
        for retry in (None, self.pending):
            write = self.save(self.pending, candidate, settlement=False, retry_remote=retry)
            sent = write.call_args.args[1]
            self.assertEqual(list(sent.status), ["pending", "pending"])
            self.assertEqual(list(sent.prediction_id), [self.pending.iloc[0].prediction_id, "new-id"])

    def test_settlement_does_not_append_unknown_ids(self):
        with patch.object(tips, "github_read_csv", return_value=(self.pending.iloc[:0], None)), \
             patch.object(tips, "github_write_csv") as write:
            with self.assertRaises(RuntimeError):
                tips._save_log(self.settled.copy(), settlement=True)
            write.assert_not_called()

    def test_duplicate_ids_raise(self):
        remote = pd.concat([self.pending, self.pending], ignore_index=True)
        with patch.object(tips, "github_read_csv", return_value=(remote, "sha")), \
             patch.object(tips, "github_write_csv") as write:
            with self.assertRaises(RuntimeError):
                tips._save_log(self.settled.copy(), settlement=True)
            write.assert_not_called()

    def test_settlement_calls_settlement_save_mode(self):
        table = Path(self.temp.name) / "teams.csv"
        pd.DataFrame(FIRST).to_csv(table, index=False)
        with patch.object(tips, "TEAM_MATCH_PATH", table), \
             patch.object(tips, "load_log", return_value=self.pending.copy()), \
             patch.object(tips, "_save_log") as save:
            tips.settle_predictions()
            self.assertTrue(save.call_args.kwargs.get("settlement"))


if __name__ == "__main__":
    unittest.main()
