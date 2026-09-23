"""Training/inference parity for calendar days since the previous PL match."""
from pathlib import Path
import sqlite3
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_data as importer
from fixture_features import _team_features
from test_sqlite_import import played


class DaysRestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real feature generation; SQLite exists only in memory, no exports.
        con = sqlite3.connect(":memory:")
        try:
            importer.initialize(con)
            for season, rows in (
                ("2025-26", [played("C", "D", "20/05/2026"),
                             played("A", "B", "24/05/2026")]),
                ("2026-27", [played("A", "C", "22/08/2026"),
                             played("E", "F", "22/08/2026"),
                             played("A", "D", "29/08/2026")]),
            ):
                importer.import_frame(con, importer.normalize_source(
                    Path(season + ".csv"), frame=pd.DataFrame(rows)))
            for rebuild in (importer.rebuild_entities, importer.rebuild_team_aggregates,
                            importer.rebuild_form, importer.rebuild_referees,
                            importer.rebuild_league, importer.rebuild_standings,
                            importer.rebuild_extended_fast, importer.rebuild_final_data_layer):
                rebuild(con)
            cls.features = pd.read_sql_query("SELECT * FROM pre_match_features", con)
            cls.history = pd.read_sql_query("SELECT * FROM team_match_stats", con)
            cls.history["match_date_dt"] = pd.to_datetime(cls.history.match_date)
        finally:
            con.close()

    def row(self, team, day):
        return self.features.loc[self.features.team.eq(team)
                                 & self.features.match_date.eq(day)].iloc[0]

    def test_within_season_uses_previous_pl_match(self):
        self.assertEqual(self.row("A", "2026-08-29").days_rest, 7.)

    def test_first_match_of_new_season_uses_prior_season(self):
        self.assertEqual(self.row("A", "2026-08-22").days_rest, 90.)

    def test_opponent_uses_own_cross_season_history(self):
        self.assertEqual(self.row("A", "2026-08-22").opp_days_rest, 94.)
        self.assertEqual(self.row("C", "2026-08-22").opp_days_rest, 90.)

    def test_no_available_history_remains_missing(self):
        for team in ("E", "F"):
            row = self.row(team, "2026-08-22")
            self.assertTrue(pd.isna(row.days_rest))
            self.assertTrue(pd.isna(row.opp_days_rest))

    def test_training_equals_inference_for_every_row_and_opponent(self):
        for row in self.features.itertuples():
            for team, opponent, venue, actual in (
                (row.team, row.opponent, row.venue, row.days_rest),
                (row.opponent, row.team, "A" if row.venue == "H" else "H", row.opp_days_rest),
            ):
                with self.subTest(team=team, date=row.match_date):
                    expected = _team_features(self.history, team, opponent, venue,
                                              row.season, row.match_date)["days_rest"]
                    if pd.isna(expected):
                        self.assertTrue(pd.isna(actual))
                    else:
                        self.assertEqual(actual, expected)

    def test_only_rest_bridges_season_not_season_averages(self):
        row = self.row("A", "2026-08-22")
        self.assertEqual(row.days_rest, 90.)
        self.assertEqual(row.matches_before, 0)
        self.assertTrue(pd.isna(row.season_fouls_committed_avg))


if __name__ == "__main__":
    unittest.main()
