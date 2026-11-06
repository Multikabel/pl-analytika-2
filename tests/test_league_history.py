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

    def test_inference_matches_training_with_reversed_csv(self):
        features, day = self.build_history()
        history = self.table("team_match_stats").iloc[::-1].copy()
        history["match_date_dt"] = pd.to_datetime(history.match_date)
        actual = _league_features(history, "2026-27", day)
        for metric in ("fouls", "corners", "yellow"):
            column = f"pl_last20_league_total_{metric}_avg_before"
            for value in features.loc[features.match_date.eq(day), column]:
                self.assertAlmostEqual(actual[column], value)


class InferenceOrderingTests(unittest.TestCase):
    def history(self, n=24):
        rows = []
        for i in range(n):
            for venue in ('H', 'A'):
                rows.append(dict(match_id=f'{i:03}', season='2026-27', venue=venue,
                                 match_date_dt=pd.Timestamp('2026-08-01') + pd.Timedelta(days=i//3),
                                 fouls_committed=float(i), corners_for=float(i+1), yellow_cards=float(i+2)))
        return pd.DataFrame(rows)

    def test_shuffled_same_day_ties_use_match_id(self):
        history = self.history()
        expected = _league_features(history, '2026-27', '2026-09-01')
        self.assertEqual(expected['pl_last20_league_total_fouls_avg_before'], 27.)
        for seed in range(3):
            self.assertEqual(expected, _league_features(history.sample(frac=1, random_state=seed), '2026-27', '2026-09-01'))

    def test_short_history_and_target_day_excluded(self):
        history = self.history(6)
        actual = _league_features(history.iloc[::-1], '2026-27', '2026-08-02')
        self.assertEqual(actual['pl_last20_league_total_fouls_avg_before'], 2.)

    def test_missing_dates_and_values_are_not_zero(self):
        history = self.history(6)
        history.loc[history.match_id.eq('005'), 'match_date_dt'] = pd.NaT
        history['fouls_committed'] = float('nan')
        actual = _league_features(history, '2026-27', '2026-09-01')
        self.assertTrue(pd.isna(actual['pl_last20_league_total_fouls_avg_before']))
        self.assertEqual(actual['pl_last20_league_total_corners_avg_before'], 6.)

    def test_invalid_date_rejected_and_invalid_values_remain_missing(self):
        with self.assertRaises(ValueError):
            _league_features(self.history(), '2026-27', 'not-a-date')
        history = self.history()
        history['corners_for'] = 'invalid'
        actual = _league_features(history, '2026-27', '2026-09-01')
        self.assertTrue(pd.isna(actual['pl_last20_league_total_corners_avg_before']))


if __name__ == "__main__":
    unittest.main()
