"""Synthetic tests: never import the application, models or persistence code."""
from pathlib import Path
import sys
import unittest
import ast
from types import SimpleNamespace
from html.parser import HTMLParser

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import data_views as views

SEASON = "2026-27"


def match(mid, home, away, values, date="2026-09-01"):
    hf, af, hy, ay, hc, ac = values
    return [dict(match_id=mid, season=SEASON, match_date=date, team=team,
                 opponent=opponent, venue=venue, **dict(zip(views.TEAM_COLUMNS.values(), numbers)))
            for team, opponent, venue, numbers in [
                (home, away, "H", [hf, af, hy, ay, hc, ac]),
                (away, home, "A", [af, hf, ay, hy, ac, hc])]]


def referee_match(i, referee="R One", season=SEASON, date=None):
    return dict(match_id=f"m{i}", season=season, match_date=date or f"2026-09-{i:02d}",
                referee=referee, home_team=f"Home{i}", away_team=f"Away{i}",
                home_fouls=i, away_fouls=i+10, total_fouls=2*i+10,
                home_yellow=i/2, away_yellow=2, total_yellow=i/2+2)


class CrossTabTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame(
            match("AL", "Arsenal", "Liverpool", [10, 20, 0, 3, 4, 8]) +
            match("LA", "Liverpool", "Arsenal", [30, 40, 5, 6, 7, 9]) +
            match("AC", "Arsenal", "Chelsea", [14, 24, 2, 5, 6, 10]))
        self.standings = pd.DataFrame([dict(season=SEASON, as_of_date="2026-09-20",
            team=team, position=pos) for team, pos in [
                ("Arsenal", 2), ("Chelsea", 3), ("Liverpool", 1), ("Everton", 4)]])

    def table(self, team="Arsenal", venue="H", history=None):
        return views.build_cross_tab(self.history if history is None else history,
                                     self.standings, SEASON, team, venue).set_index("Tým")

    def test_home_preserves_all_six_perspective_columns(self):
        self.assertEqual(self.table().loc["Liverpool", list(views.TEAM_COLUMNS)].tolist(),
                         [10, 20, 0, 3, 4, 8])

    def test_away_preserves_all_six_perspective_columns(self):
        self.assertEqual(self.table(venue="A").loc["Liverpool", list(views.TEAM_COLUMNS)].tolist(),
                         [40, 30, 6, 5, 9, 7])

    def test_selected_row_uses_only_split_averages(self):
        self.assertEqual(self.table().loc["Arsenal", list(views.TEAM_COLUMNS)].tolist(),
                         [12, 22, 1, 4, 5, 9])
        self.assertEqual(self.table(venue="A").loc["Arsenal", "F+"], 40)

    def test_total_mode_each_team_own_split(self):
        table = self.table(team=None)
        self.assertEqual(table.loc["Arsenal", "F+"], 12)
        self.assertEqual(table.loc["Liverpool", "F+"], 30)
        self.assertTrue(pd.isna(table.loc["Chelsea", "F+"]))

    def test_missing_meeting_not_zero(self):
        self.assertTrue(self.table().loc["Everton", list(views.TEAM_COLUMNS)].isna().all())
        self.assertTrue(pd.isna(self.table(venue="A").loc["Chelsea", "F+"]))

    def test_measured_zero_stays_zero(self):
        self.assertEqual(self.table().loc["Liverpool", "ŽK+"], 0)

    def test_duplicate_meeting_is_unavailable(self):
        for extra in [self.history.iloc[:1], self.history.iloc[:2].assign(match_id="other")]:
            with self.subTest(extra=len(extra)):
                table = self.table(history=pd.concat([self.history, extra], ignore_index=True))
                self.assertTrue(table.loc["Liverpool", list(views.TEAM_COLUMNS)].isna().all())

    def test_inconsistent_pair_is_unavailable(self):
        for column, value in [("opponent", "Wrong"), ("fouls_suffered", 99), ("match_date", "2026-09-02")]:
            changed = self.history.copy()
            changed.loc[1, column] = value
            with self.subTest(column=column):
                self.assertTrue(pd.isna(self.table(history=changed).loc["Liverpool", "F+"]))

    def test_missing_pair_is_unavailable(self):
        self.assertTrue(pd.isna(self.table(history=self.history.drop(index=1)).loc["Liverpool", "F+"]))

    def test_default_order_and_latest_season_table(self):
        old = self.standings.assign(as_of_date="2026-08-01", position=[4, 3, 2, 1])
        previous = self.standings.assign(season="2025-26", as_of_date="2027-01-01")
        self.standings = pd.concat([old, previous, self.standings], ignore_index=True)
        table = self.table()
        self.assertEqual(table.index.tolist(), ["Liverpool", "Arsenal", "Chelsea", "Everton"])
        self.assertEqual(str(table.attrs["as_of_date"].date()), "2026-09-20")

    def test_short_names_only_presentation(self):
        self.history = self.history.replace("Arsenal", "Manchester United")
        self.standings = self.standings.replace("Arsenal", "Manchester United")
        table = self.table(team="Manchester United")
        self.assertEqual(table.loc["Liverpool", "F+"], 10)
        self.assertIn("Manchester United", table.index)
        self.assertEqual(views.short_team_name("Manchester United"), "Man Utd")
        self.assertEqual(views.short_team_name("Arsenal"), "Arsenal")
        styled = views.cross_tab_styles(table.reset_index(), "Manchester United")
        self.assertTrue(styled.loc[1].str.contains("background-color").all())
        self.assertTrue(styled.loc[1].str.contains("; color: #17212b", regex=False).all())
        self.assertTrue(styled.loc[0].eq("").all())

    def test_inputs_are_not_mutated(self):
        h, s = self.history.copy(deep=True), self.standings.copy(deep=True)
        self.table()
        pd.testing.assert_frame_equal(h, self.history)
        pd.testing.assert_frame_equal(s, self.standings)

    def test_rendered_averages_matches_missing_and_zero(self):
        class Cells(HTMLParser):
            def __init__(self):
                super().__init__()
                self.values = {}
                self.cell = None

            def handle_starttag(self, tag, attrs):
                if tag == "td":
                    self.cell = dict(attrs).get("id")

            def handle_data(self, data):
                if self.cell:
                    self.values[self.cell] = data

            def handle_endtag(self, tag):
                if tag == "td":
                    self.cell = None

        for selected in [None, "Arsenal"]:
            with self.subTest(selected=selected):
                table = views.build_cross_tab(self.history, self.standings, SEASON, selected)
                before = table.copy(deep=True)
                styled = views.cross_tab_display(table, selected).set_uuid("test")
                cells = Cells()
                cells.feed(styled.to_html())
                # Liverpool row first, selected Arsenal second, Everton last.
                self.assertEqual(cells.values["T_test_row1_col2"], "12.0")
                self.assertEqual(cells.values["T_test_row0_col2"], "30.0" if selected is None else "10")
                self.assertEqual(cells.values["T_test_row3_col2"], "—")
                if selected is not None:
                    self.assertEqual(cells.values["T_test_row0_col4"], "0")
                pd.testing.assert_frame_equal(table, before)
                # Test the actual dataframe handed to Streamlit, not only Styler HTML:
                # Arrow nulls would otherwise render as None despite na_rep="—".
                self.assertEqual(styled.data.loc[3, "F+"], "—")
                self.assertEqual(styled.data.loc[1, "F+"], "12.0")
                self.assertFalse(styled.data[list(views.TEAM_COLUMNS)].isna().any().any())
                self.assertNotIn("None", styled.data[list(views.TEAM_COLUMNS)].to_numpy())
                if selected is not None:
                    self.assertEqual(styled.data.loc[0, "ŽK+"], "0")
                    self.assertEqual(styled.data.loc[0, "F+"], "10")


class RefereeTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame([referee_match(i) for i in range(1, 8)])

    def test_unique_match_count_and_means(self):
        data = pd.concat([self.history, self.history.iloc[:1]], ignore_index=True)
        summary = views.build_referee_summary(data, SEASON).iloc[0]
        self.assertEqual(summary["Zápasy"], 7)
        self.assertEqual(summary["F D"], 4)
        self.assertEqual(summary["F H"], 14)
        self.assertEqual(summary["F Σ"], 18)
        self.assertEqual(summary["ŽK D"], 2)
        self.assertEqual(summary["ŽK H"], 2)
        self.assertEqual(summary["ŽK Σ"], 4)

    def test_form_last_five_current_season_only(self):
        old = pd.DataFrame([referee_match(99, season="2025-26", date="2027-01-01")])
        data = pd.concat([self.history.iloc[::-1], old], ignore_index=True)
        summary, _ = views.build_referee_detail(data, SEASON, "R One")
        self.assertEqual(summary.iloc[0]["Zápasy"], 7)
        self.assertEqual(summary.iloc[1]["Zápasy"], 5)
        self.assertEqual(summary.iloc[1]["F D"], 5)

    def test_form_uses_fewer_than_five(self):
        summary, _ = views.build_referee_detail(self.history.iloc[:3], SEASON, "R One")
        self.assertEqual(summary.iloc[1]["Období"], "Forma · 3 zápasy")
        self.assertEqual(summary.iloc[1]["Zápasy"], 3)
        self.assertEqual(summary.iloc[1]["F D"], 2)

    def test_form_label_czech_declension(self):
        for count, word in [(1, "zápas"), (2, "zápasy"), (3, "zápasy"),
                            (4, "zápasy"), (5, "zápasů")]:
            with self.subTest(count=count):
                summary, _ = views.build_referee_detail(self.history.iloc[:count], SEASON, "R One")
                self.assertEqual(summary.iloc[1]["Období"], f"Forma · {count} {word}")

    def test_history_chronological_with_id_tiebreak(self):
        data = self.history.iloc[::-1].copy()
        data.loc[data.match_id.eq("m2"), "match_date"] = "2026-09-01"
        _, detail = views.build_referee_detail(data, SEASON, "R One")
        self.assertEqual(detail["Domácí"].tolist(), [f"Home{i}" for i in range(1, 8)])
        self.assertTrue(detail.Datum.is_monotonic_increasing)

    def test_summary_count_descending_name_ascending(self):
        data = pd.DataFrame([referee_match(1, "Z Ref"), referee_match(2, "A Ref"),
                             referee_match(3, "B Ref"), referee_match(4, "B Ref")])
        summary = views.build_referee_summary(data, SEASON)
        self.assertEqual(summary["Rozhodčí"].tolist(), ["B Ref", "A Ref", "Z Ref"])

    def test_conflicting_duplicate_not_arbitrarily_selected(self):
        conflict = self.history.iloc[:1].assign(home_fouls=999)
        summary = views.build_referee_summary(pd.concat([self.history, conflict]), SEASON)
        self.assertEqual(summary.iloc[0]["Zápasy"], 6)
        self.assertEqual(summary.iloc[0]["F D"], 4.5)

    def test_styling_same_column_unrounded_and_missing_neutral(self):
        detail = pd.DataFrame({"F D": [10, 10.04, None], "F H": [10, 10, 10],
                               "ŽK D": [1, 1, 1], "ŽK H": [1, 1, 1]})
        means = {"F D": 10.02, "F H": 9, "ŽK D": 1, "ŽK H": float("nan")}
        styles = views.referee_cell_styles(detail, means)
        self.assertIn("#f7e6e6", styles.loc[0, "F D"])
        self.assertIn("#e5f2e8", styles.loc[1, "F D"])
        self.assertIn("; color: #17212b", styles.loc[0, "F D"])
        self.assertIn("; color: #17212b", styles.loc[1, "F D"])
        self.assertEqual(styles.loc[2, "F D"], "")
        self.assertTrue(styles["F H"].str.contains("#e5f2e8").all())
        self.assertTrue(styles["F H"].str.contains("; color: #17212b", regex=False).all())
        self.assertTrue(styles["ŽK D"].eq("").all())
        self.assertTrue(styles["ŽK H"].eq("").all())

    def test_referee_inputs_not_mutated(self):
        before = self.history.copy(deep=True)
        views.build_referee_summary(self.history, SEASON)
        views.build_referee_detail(self.history, SEASON, "R One")
        pd.testing.assert_frame_equal(before, self.history)

    def test_referee_count_label_is_display_only(self):
        # Execute only the column configuration, never the app or its pipeline imports.
        source = Path(__file__).resolve().parents[1] / "app/app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assignments = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target = node.targets[0]
            root = target.value if isinstance(target, ast.Subscript) else target
            if isinstance(root, ast.Name) and root.id == "ref_config":
                assignments.append(node)
        self.assertTrue(assignments)
        config = SimpleNamespace(NumberColumn=lambda label, **kw: dict(label=label, **kw),
                                 TextColumn=lambda label, **kw: dict(label=label, **kw))
        namespace = {"st": SimpleNamespace(column_config=config), "REF_COLUMNS": views.REF_COLUMNS}
        exec(compile(ast.Module(body=sorted(assignments, key=lambda n: n.lineno),
                                type_ignores=[]), "<column-config-only>", "exec"), namespace)
        rendered = namespace["ref_config"]
        self.assertEqual(rendered["Zápasy"]["label"], "Z")
        self.assertLessEqual(rendered["Zápasy"]["width"], 40)
        self.assertEqual(rendered["Zápasy"]["format"], "%d")
        summary = views.build_referee_summary(self.history, SEASON)
        self.assertIn("Zápasy", summary.columns)
        self.assertNotIn("Z", summary.columns)
        self.assertEqual(summary.iloc[0]["Zápasy"], 7)


if __name__ == "__main__":
    unittest.main()
