"""End-to-end importer regressions using synthetic sources and temporary SQLite."""
import contextlib
import io
import hashlib
import os
import json
import subprocess
import time
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_data as importer


def played(home="A", away="B", date="01/08/2026", **changes):
    row = dict(Div="E0", Date=date, HomeTeam=home, AwayTeam=away,
               FTHG=2, FTAG=1, FTR="H", HTHG=1, HTAG=0, HTR="H",
               Referee="Synthetic Ref", HF=12, AF=9, HC=6, AC=4, HY=2, AY=1,
               HR=0, AR=0, HS=10, AS=8, HST=4, AST=3, HxG=1.8, AxG=.9,
               B365H=2.)
    row.update(changes)
    return row


class SQLiteImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.raw = self.base / "data/raw"
        self.tables = self.base / "data/tables"
        self.db = self.base / "data/test.sqlite"
        self.fixtures = self.base / "data/fixtures"
        for folder in (self.raw, self.tables, self.fixtures, self.base / "data/predictions"):
            folder.mkdir(parents=True, exist_ok=True)
        for name in ("BASE", "RAW", "TABLES", "DB"):
            self.enterContext(patch.object(importer, name, {
                "BASE": self.base, "RAW": self.raw, "TABLES": self.tables, "DB": self.db}[name]))
        # Pin the season clock without changing datetime used in source parsing.
        self.enterContext(patch.object(importer, "datetime", wraps=importer.datetime))
        importer.datetime.now.return_value = __import__("datetime").datetime(2026, 9, 21)
        self.enterContext(patch("requests.sessions.Session.request",
                                side_effect=AssertionError("Network forbidden")))
        self.archives = {}
        for name in ("prediction_log.csv", "model_prediction_log.csv"):
            path = self.base / "data/predictions" / name
            path.write_bytes(b"immutable synthetic archive\r\n")
            self.archives[path] = path.read_bytes()
        teams = list("ABCDEFGHIJKLMNOPQRST")
        self.pairs = [(h, a) for h in teams for a in teams if h != a]
        schedule = pd.DataFrame([dict(home_team=h, away_team=a,
                                      match_round=i // 10 + 1,
                                      match_date="2026-08-01", season="2026-27")
                                 for i, (h, a) in enumerate(self.pairs)])
        schedule.to_csv(self.fixtures / "premier_league_2026-27.csv", index=False)

    def tearDown(self):
        for path, expected in self.archives.items():
            self.assertEqual(path.read_bytes(), expected)

    def source(self, rows, season="2026-27"):
        path = self.raw / f"{season}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def run_import(self):
        connections = []
        connect = sqlite3.connect
        def tracked(*args, **kwargs):
            con = connect(*args, **kwargs)
            connections.append(con)
            return con
        try:
            with contextlib.redirect_stdout(io.StringIO()), patch.object(sqlite3, "connect", tracked):
                importer.run(self.raw)
        finally:
            # Legacy run() leaks connections on failure; release temp files on Windows.
            for con in connections:
                con.close()

    def state(self):
        paths = [self.db] + sorted(self.tables.glob("*.csv"))
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}

    def table(self, name):
        with contextlib.closing(sqlite3.connect(self.db)) as con:
            return pd.read_sql_query(f'SELECT * FROM "{name}"', con)

    def check_core(self, matches):
        for name, count in (("matches", matches), ("team_match_stats", 2 * matches),
                            ("referee_match_stats", matches), ("pre_match_features", 2 * matches),
                            ("match_odds", matches)):
            actual = self.table(name)
            self.assertEqual(len(actual), count, name)
            expected = pd.read_csv(io.StringIO(actual.to_csv(index=False)))
            pd.testing.assert_frame_equal(expected, pd.read_csv(self.tables / f"{name}.csv"))

    def test_date_change_replaces_old_match(self):
        self.source([played()]); self.run_import()
        self.source([played(date="02/08/2026")]); self.run_import()
        self.check_core(1)
        self.assertEqual(self.table("matches").match_date.tolist(), ["2026-08-02"])

    def test_identical_import_is_idempotent(self):
        self.source([played(), played("C", "D")]); self.run_import()
        before = {n: self.table(n) for n in ("matches", "team_match_stats", "referee_match_stats", "pre_match_features", "match_odds")}
        self.run_import(); self.check_core(2)
        for name, expected in before.items():
            pd.testing.assert_frame_equal(expected, self.table(name))

    def test_bad_sources_leave_database_and_exports_unchanged(self):
        self.source([played(), played("C", "D")]); self.run_import()
        before = self.state()
        frame = pd.DataFrame([played(), played("C", "D")])
        variants = {
            "empty": "", "headers": frame.iloc[:0].to_csv(index=False),
            "missing_team": frame.drop(columns="AwayTeam").to_csv(index=False),
            "missing_goals": frame.drop(columns=["FTHG", "FTAG"]).to_csv(index=False),
            "missing_fouls": frame.drop(columns=["HF", "AF"]).to_csv(index=False),
            "removed_played": frame.iloc[1:].to_csv(index=False),
            "bad_date": pd.DataFrame([played(date="bad"), played("C", "D")]).to_csv(index=False),
            "unknown_fixture": pd.DataFrame([played("Unknown", "B"), played("C", "D")]).to_csv(index=False),
            "future_only": pd.DataFrame([played(FTHG=None, FTAG=None)]).to_csv(index=False),
        }
        for label, content in variants.items():
            with self.subTest(source=label):
                (self.raw / "2026-27.csv").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.run_import()
                self.assertEqual(self.state(), before)

    def test_invalid_second_season_does_not_write_first(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source([played(date="02/08/2026")])
        self.source([{"Date": "01/08/2027"}], "2027-28")
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)

    def test_aggregation_failure_rolls_back_everything(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source([played(date="02/08/2026")])
        # Fail after the real final feature rebuild, including its SQL writes.
        original = importer.rebuild_final_data_layer
        def fail(con):
            original(con)
            self.assertTrue(con.in_transaction, "Feature writes must not commit the import")
            raise RuntimeError("synthetic aggregation failure")
        with patch.object(importer, "rebuild_final_data_layer", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "synthetic aggregation"):
                self.run_import()
        self.assertEqual(self.state(), before)

    def test_export_failure_preserves_database_and_exports(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source([played(date="02/08/2026")])
        original = pd.DataFrame.to_csv
        def fail(frame, path=None, *args, **kwargs):
            if path is not None and Path(path).name == "team_match_stats.csv":
                raise OSError("synthetic export failure")
            return original(frame, path, *args, **kwargs)
        with patch.object(pd.DataFrame, "to_csv", fail):
            with self.assertRaisesRegex(OSError, "synthetic export"):
                self.run_import()
        self.assertEqual(self.state(), before)

    def historical(self):
        return [played(h, a, "01/05/2026" if (h, a) == ("A", "B") else "01/08/2025")
                for h, a in self.pairs]

    def test_complete_history_removes_stale_fixture_and_rebuilds_future(self):
        history = self.historical()
        self.source(history, "2025-26"); self.source([played()]); self.run_import()
        before_future = self.table("pre_match_features").query("season == '2026-27' and team == 'A'").iloc[0]
        future_matches = self.table("matches").query("season == '2026-27'").copy()
        # A legacy extra date for known teams, absent from the complete source.
        # Roster changes are intentionally no longer authorized by replacement.
        stale = self.base / "2025-26.csv"
        pd.DataFrame([played("A", "C", "02/08/2025")]).to_csv(stale, index=False)
        stale_id = importer.make_match_id("2025-26", "2025-08-02", "A", "C")
        with contextlib.closing(sqlite3.connect(self.db)) as con:
            with con:
                importer.import_frame(con, importer.normalize_source(stale))
        history[0] = played("A", "B", "02/05/2026", HF=24)
        self.source(history, "2025-26")
        (self.raw / "2026-27.csv").unlink()
        self.run_import(); self.check_core(381)
        self.assertNotIn(stale_id, set(self.table("matches").match_id))
        pd.testing.assert_frame_equal(future_matches.reset_index(drop=True),
                                      self.table("matches").query("season == '2026-27'").reset_index(drop=True))
        after_future = self.table("pre_match_features").query("season == '2026-27' and team == 'A'").iloc[0]
        self.assertNotEqual(before_future.pl_last5_fouls_committed_avg, after_future.pl_last5_fouls_committed_avg)

    def test_incomplete_history_is_rejected(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source(self.historical()[:-1], "2025-26")
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)

    def test_publication_failure_restores_all_published_files(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source([played(date="02/08/2026")])
        replace = os.replace
        attempted = []
        def fail(source, target):
            if Path(source).parent.name != "backups":
                attempted.append(Path(target))
                if Path(target) == self.db:
                    raise OSError("synthetic publication failure")
            return replace(source, target)
        with patch("os.replace", side_effect=fail):
            with self.assertRaisesRegex(OSError, "synthetic publication"):
                self.run_import()
        self.assertGreater(len(attempted), 1)
        self.assertEqual(self.state(), before)

    def test_second_season_database_failure_rolls_back(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source(self.historical(), "2025-26")
        original = importer.import_frame
        seen = []
        def fail(con, frame):
            seen.append(frame.iloc[0]._season)
            original(con, frame)
            if len(seen) == 2:
                raise RuntimeError("synthetic second season failure")
        with patch.object(importer, "import_frame", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "synthetic second season"):
                self.run_import()
        self.assertEqual(seen, ["2025-26", "2026-27"])
        self.assertEqual(self.state(), before)

    def test_invalid_schedule_and_lost_optional_stat_are_rejected(self):
        self.source([played()]); self.run_import()
        before = self.state()
        self.source([played(HS=None)])
        with self.assertRaisesRegex(ValueError, "lost statistic HS"):
            self.run_import()
        self.assertEqual(self.state(), before)
        self.source([played()])
        schedule = self.fixtures / "premier_league_2026-27.csv"
        frame = pd.read_csv(schedule)
        frame.iloc[:-1].to_csv(schedule, index=False)
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)

    def test_renamed_historical_team_is_rejected(self):
        history = pd.DataFrame(self.historical())
        self.source(history, "2025-26"); self.run_import()
        before = self.state()
        renamed = history.replace({"HomeTeam": {"A": "TypoA"}, "AwayTeam": {"A": "TypoA"}})
        self.assertEqual(len(renamed), 380)
        self.source(renamed, "2025-26")
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)

    def test_postponed_unplayed_without_date_is_excluded(self):
        self.source([played(), played("C", "D")]); self.run_import()
        postponed = played("E", "F", None, FTHG=None, FTAG=None)
        self.source([played(date="02/08/2026"), played("C", "D"), postponed])
        self.run_import(); self.check_core(2)
        self.assertNotIn("E", set(self.table("matches").home_team))
        before = self.state()
        # A previously played fixture cannot be disguised as an unplayed one.
        self.source([played("A", "B", None, FTHG=None, FTAG=None), played("C", "D")])
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)
        # Unplayed identities still need to belong to the authority schedule.
        self.source([played(date="02/08/2026"), played("C", "D"), dict(postponed, HomeTeam="Unknown")])
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.state(), before)

    def test_overlapping_process_imports_preserve_both_seasons(self):
        history = self.historical()
        self.source(history, "2025-26"); self.source([played()]); self.run_import()
        current_raw, historical_raw = self.base / "current", self.base / "history"
        current_raw.mkdir(); historical_raw.mkdir()
        pd.DataFrame([played(date="02/08/2026")]).to_csv(current_raw / "2026-27.csv", index=False)
        history[0] = played("A", "B", "02/05/2026", HF=24)
        pd.DataFrame(history).to_csv(historical_raw / "2025-26.csv", index=False)
        # Workers execute the real importer in separate interpreters. Hooks only
        # pause publication and report when the real DB backup has been created.
        worker = r'''
import sys, json, pathlib, time, os
from datetime import datetime
sys.dont_write_bytecode = True
sys.path[:0] = json.loads(sys.argv[1])
import update_data as u
base, raw, tag, repo = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), sys.argv[4], pathlib.Path(sys.argv[5])
def guard(event, args):
    if event == 'open':
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and not isinstance(path, int) and pathlib.Path(path).resolve().is_relative_to(repo):
            raise RuntimeError('Repository write blocked in import worker')
    if event == 'sqlite3.connect' and repo.as_posix().lower() in str(args[0]).replace(chr(92), '/').lower():
        raise RuntimeError('Production SQLite blocked in import worker')
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise RuntimeError('Network blocked in import worker')
sys.addaudithook(guard)
class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 21)
u.datetime = FrozenDatetime
u.BASE, u.DB, u.TABLES = base, base / 'data/test.sqlite', base / 'data/tables'
initialize, publish = u.initialize, u.publish_import
def initialized(con):
    initialize(con)
    (base / (tag + '.snapshot')).touch()
def gated_publish(*args):
    (base / (tag + '.ready')).touch()
    deadline = time.monotonic() + 90
    while not (base / (tag + '.release')).exists():
        if time.monotonic() > deadline:
            raise TimeoutError('Publication gate timed out')
        time.sleep(.02)
    publish(*args)
u.initialize, u.publish_import = initialized, gated_publish
(base / (tag + '.started')).touch()
u.run(raw)
'''
        processes = []
        def launch(tag, raw):
            output = self.enterContext((self.base / (tag + ".log")).open("w"))
            process = subprocess.Popen([sys.executable, "-B", "-W", "ignore", "-c", worker,
                json.dumps(sys.path), str(self.base), str(raw), tag,
                str(Path(__file__).resolve().parents[1])], stdout=output, stderr=output)
            processes.append(process)
            return process
        def wait_for(name, timeout=60):
            deadline = time.monotonic() + timeout
            while not (self.base / name).exists():
                if time.monotonic() > deadline:
                    self.fail(f"Worker marker missing: {name}")
                time.sleep(.02)
        try:
            first = launch("first", current_raw)
            wait_for("first.ready")
            second = launch("second", historical_raw)
            wait_for("second.started")
            deadline = time.monotonic() + 3
            while not (self.base / "second.snapshot").exists() and time.monotonic() < deadline:
                time.sleep(.02)
            early_snapshot = (self.base / "second.snapshot").exists()
            (self.base / "first.release").touch()
            self.assertEqual(first.wait(timeout=60), 0, (self.base / "first.log").read_text())
            wait_for("second.ready")
            (self.base / "second.release").touch()
            self.assertEqual(second.wait(timeout=60), 0, (self.base / "second.log").read_text())
            matches = self.table("matches")
            self.assertEqual(matches.query("season == '2026-27'").match_date.tolist(), ["2026-08-02"])
            historic = self.table("team_match_stats").query("season == '2025-26' and team == 'A' and opponent == 'B' and venue == 'H'")
            self.assertEqual(historic.fouls_committed.tolist(), [24.])
            self.assertFalse(early_snapshot, "Second import took a stale snapshot while first held publication")
            self.check_core(381)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
if __name__ == "__main__":
    unittest.main()
