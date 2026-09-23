"""Day-boundary league history through the real, isolated SQLite importer."""
from datetime import date, timedelta
import unittest

import pandas as pd

import test_sqlite_import as sqlite_tests
from fixture_features import _league_features


class LeagueHistoryTests(unittest.TestCase):
    setUp = sqlite_tests.SQLiteImportTests.setUp
    tearDown = sqlite_tests.SQLiteImportTests.tearDown
    source = sqlite_tests.SQLiteImportTests.source
    run_import = sqlite_tests.SQLiteImportTests.run_import
    table = sqlite_tests.SQLiteImportTests.table

    def build_history(self, count=21):
        rows = []
        for i in range(count + 3):
            day = date(2026, 8, 1) + timedelta(days=min(i, count))
            # Very different same-day results make accidental inclusion visible.
            value = i + 1 if i < count else 100 + i
            rows.append(sqlite_tests.played(*self.pairs[i], date=day.strftime("%d/%m/%Y"),
                               Time="12:30" if i == count else "15:00",
                               HF=value, AF=value, HC=value, AC=value,
                               HY=value, AY=value, FTHG=value, FTAG=value))
        self.source(rows)
        self.run_import()
        return self.table("pre_match_features"), day.isoformat()

    def assert_metrics(self, rows, expected):
        for metric in ("fouls", "corners", "yellow", "goals"):
            column = f"pl_last20_league_total_{metric}_avg_before"
            for value in rows[column]:
                self.assertAlmostEqual(value, expected, msg=column)

    def test_early_and_late_kickoffs_share_prior_day_last20(self):
        features, day = self.build_history()
        current = features[features.match_date.eq(day)]
        self.assertEqual(len(current), 6)
        # Prior totals are 2..42; discard the oldest, retaining 4..42.
        self.assert_metrics(current, 23.)

    def test_short_history_includes_previous_days(self):
        features, day = self.build_history(count=3)
        self.assert_metrics(features[features.match_date.eq(day)], 4.)

    def test_first_day_has_no_history(self):
        features, day = self.build_history(count=0)
        columns = [f"pl_last20_league_total_{m}_avg_before"
                   for m in ("fouls", "corners", "yellow", "goals")]
        self.assertTrue(features[columns].isna().all().all())

    def test_matches_existing_inference_day_boundary(self):
        features, day = self.build_history()
        history = self.table("team_match_stats").sort_values(["match_date", "match_id"])
        history["match_date_dt"] = pd.to_datetime(history.match_date)
        expected = _league_features(history, "2026-27", day)
        for metric in ("fouls", "corners", "yellow"):
            column = f"pl_last20_league_total_{metric}_avg_before"
            for value in features.loc[features.match_date.eq(day), column]:
                self.assertAlmostEqual(value, expected[column], msg=column)


if __name__ == "__main__":
    unittest.main()
