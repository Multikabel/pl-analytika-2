"""Synthetic pre-match safety and deterministic evidence/ranking regressions."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pattern_engine import analyze_patterns_v2
from pattern_matcher import match_patterns, evidence_level, rank_patterns


FIXTURE = dict(home_team="Alpha", away_team="Beta", season="2026-27",
               match_date="2026-10-10", kickoff_time="17:30", referee="M Oliver")


def history(signs=(1, 1, 1, 1), current=False):
    matches, stats = [], []
    for year, sign in zip(range(2022, 2022 + len(signs)), signs):
        season = f"{year}-{str(year + 1)[-2:]}"
        start = date(year, 8, 1)
        saturday = start + timedelta(days=(5 - start.weekday()) % 7)
        for subject, venue in (("Alpha", "H"), ("Beta", "A"), ("Alpha", "A"), ("Beta", "H")):
            for i in range(7):
                group = i < 5
                day = saturday + timedelta(days=7 * i + (0 if group else 1))
                opponent = f"Other{subject}{venue}{i}"
                home, away = (subject, opponent) if venue == "H" else (opponent, subject)
                mid = f"{year}-{subject}-{venue}-{i}"
                matches.append(dict(match_id=mid, season=season, match_date=day.isoformat(),
                                    kickoff_time="17:30" if group else "15:00",
                                    home_team=home, away_team=away, referee="M Oliver"))
                for team, opp, side in ((home, away, "H"), (away, home, "A")):
                    # Wrong venue has the opposite effect, exposing venue swaps.
                    expected_venue = "H" if subject == "Alpha" else "A"
                    direction = sign if venue == expected_venue else -sign
                    value = 5 + direction * 2 if group and team == subject else 5
                    stats.append(dict(match_id=mid, season=season, team=team, opponent=opp,
                                      venue=side, fouls_committed=value,
                                      yellow_cards=value, corners_for=value))
    m, t = pd.DataFrame(matches), pd.DataFrame(stats)
    if current:
        extra_m, extra_t = history((1,))
        extra_m = extra_m.iloc[[0, 5]].copy()
        extra_m["match_date"] = ["2026-08-22", "2026-08-23"]
        extra_m["season"] = "2026-27"
        extra_t = extra_t[extra_t.match_id.isin(extra_m.match_id)].copy()
        extra_t["season"] = "2026-27"
        extra_t["fouls_committed"] = 99  # Current opposing/large values must not invent OOS tests.
        extra_m["match_id"] = "current-" + extra_m.match_id
        extra_t["match_id"] = "current-" + extra_t.match_id
        m, t = pd.concat([m, extra_m], ignore_index=True), pd.concat([t, extra_t], ignore_index=True)
    return m, t


class MatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.t = history()
        cls.result = match_patterns(cls.m, cls.t, FIXTURE)

    def test_team_weekday_and_three_metrics(self):
        rows = self.result.patterns.query("pattern_type == 'team_weekday'")
        self.assertEqual(set(rows.weekday), {"Saturday"})
        self.assertEqual(set(rows.metric), {"fouls", "yellow_cards", "corners"})
        self.assertEqual(len(rows), 6)

    def test_venues_and_home_away_roles(self):
        teams = self.result.patterns[self.result.patterns.role.ne("referee")]
        self.assertEqual(set(zip(teams.subject, teams.venue, teams.role)),
                         {("Alpha", "H", "home"), ("Beta", "A", "away")})
        self.assertTrue(teams.direction.eq("up").all())

    def test_daypart_matches_existing_family(self):
        rows = self.result.patterns[self.result.patterns.pattern_type.str.endswith("daypart")]
        self.assertEqual(set(rows.daypart), {"late"})
        self.assertEqual(len(rows), 9)

    def test_referee_exact_identity(self):
        rows = self.result.patterns.query("role == 'referee'")
        self.assertEqual(set(rows.subject), {"M Oliver"})
        self.assertEqual(len(rows), 6)

    def test_unknown_referee_never_fuzzy_matches(self):
        result = match_patterns(self.m, self.t, dict(FIXTURE, referee="O Oliver"))
        self.assertFalse(result.patterns.role.eq("referee").any())
        self.assertEqual(len(result.patterns), 12)

    def test_missing_referee_safe(self):
        for missing in (None, "", np.nan):
            result = match_patterns(self.m, self.t, dict(FIXTURE, referee=missing))
            self.assertEqual(len(result.patterns), 12)

    def test_only_prematch_fixture_fields_are_needed(self):
        self.assertEqual(len(self.result.patterns), 18)
        ignored = dict(FIXTURE, actual_value=999, home_goals=99, result="H")
        pd.testing.assert_frame_equal(match_patterns(self.m, self.t, ignored).patterns,
                                      self.result.patterns)

    def test_future_same_day_and_target_results_cannot_change_output(self):
        future_m = self.m.iloc[:3].copy()
        future_m["match_date"] = ["2026-10-10", "2026-10-10", "2026-10-11"]
        future_m["kickoff_time"] = ["12:30", "20:00", "12:30"]
        future_m["season"] = "2026-27"
        future_t = self.t[self.t.match_id.isin(future_m.match_id)].copy()
        future_t["season"] = "2026-27"
        future_t[["fouls_committed", "yellow_cards", "corners_for"]] = 999
        future_m["match_id"] = "future-" + future_m.match_id
        future_t["match_id"] = "future-" + future_t.match_id
        # Same target identity with an inconsistent earlier date is excluded too.
        target_m = pd.DataFrame([dict(match_id="target", season="2026-27", match_date="2026-10-09",
                                      kickoff_time="12:30", home_team="Alpha", away_team="Beta", referee="M Oliver")])
        target_t = pd.DataFrame([dict(match_id="target", season="2026-27", team=team, opponent=opp,
                                      venue=venue, fouls_committed=999, yellow_cards=999, corners_for=999)
                                 for team, opp, venue in (("Alpha", "Beta", "H"), ("Beta", "Alpha", "A"))])
        result = match_patterns(pd.concat([self.m, future_m, target_m]),
                                pd.concat([self.t, future_t, target_t]), FIXTURE)
        pd.testing.assert_frame_equal(result.patterns, self.result.patterns)
        self.assertEqual(result.quality, self.result.quality)

    def test_historical_replay_excludes_later_seasons(self):
        fixture = dict(FIXTURE, season="2024-25", match_date="2024-10-12")
        full = match_patterns(self.m, self.t, fixture)
        small_m = self.m[self.m.season.ne("2025-26")]
        small_t = self.t[self.t.season.ne("2025-26")]
        pd.testing.assert_frame_equal(full.patterns, match_patterns(small_m, small_t, fixture).patterns)

    def test_up_down_symmetric(self):
        for direction in ("up", "down"):
            self.assertEqual(evidence_level(direction, 4, 2, 2, 0, 0)[0], "strong_candidate")
            self.assertEqual(evidence_level(direction, 3, 1, 1, 0, 0)[0], "supported")

    def test_mixed_remains_mixed_even_with_two_hits(self):
        self.assertEqual(evidence_level("mixed", 4, 2, 2, 0, 0)[0], "mixed")

    def test_one_of_one_not_strong(self):
        self.assertEqual(evidence_level("up", 4, 1, 1, 0, 0)[0], "supported")

    def test_two_of_two_not_enough_without_history_or_direction(self):
        self.assertEqual(evidence_level("up", 2, 2, 2, 0, 0)[0], "supported")
        self.assertEqual(evidence_level("up", 1, 2, 2, 0, 0)[0], "weak")
        self.assertEqual(evidence_level("neutral", 4, 2, 2, 0, 0)[0], "weak")

    def test_strong_boundaries_and_neutral_not_hit(self):
        self.assertEqual(evidence_level("down", 3, 2, 2, 0, 0)[0], "strong_candidate")
        self.assertEqual(evidence_level("up", 3, 2, 1, 1, 0)[0], "weak")
        self.assertEqual(evidence_level("up", 3, 2, 1, 0, 1)[0], "weak")
        self.assertEqual(evidence_level("up", 3, 0, 0, 0, 0)[0], "weak")

    def test_current_insufficient_does_not_invent_miss(self):
        result = match_patterns(*history(current=True), FIXTURE)
        a = result.patterns.query("subject == 'Alpha' and pattern_type == 'team_weekday'")
        self.assertTrue(a.evidence_level.eq("strong_candidate").all())
        self.assertTrue(a.current_status.eq("pending").all())
        self.assertTrue(a.current_N_group.eq(1).all())
        self.assertTrue(a.current_sample_class.eq("insufficient").all())
        self.assertTrue(a.oos_misses.eq(0).all())
        self.assertTrue(a.oos_tests.eq(2).all())

    def test_full_result_retains_weak_and_mixed(self):
        # Alternate historical signs -> mixed; referee totals here cancel -> weak.
        result = match_patterns(*history((1, -1, 1, -1)), FIXTURE)
        self.assertEqual(len(result.patterns), 18)
        self.assertEqual(set(result.patterns.evidence_level), {"mixed", "weak"})

    def test_ranking_deterministic_with_shuffled_inputs(self):
        result = match_patterns(self.m.sample(frac=1, random_state=4),
                                self.t.sample(frac=1, random_state=8), FIXTURE)
        pd.testing.assert_frame_equal(result.patterns, self.result.patterns)
        pd.testing.assert_frame_equal(rank_patterns(result.patterns.sample(frac=1, random_state=2)),
                                      self.result.patterns)

    def test_ranking_priorities_are_lexicographic(self):
        rows = self.result.patterns.iloc[:7].copy().reset_index(drop=True)
        rows["label"] = list("ABCDEFG")
        rows["evidence_level"] = ["mixed", "weak", "supported", "supported", "supported", "supported", "strong_candidate"]
        rows["oos_tests"] = [100, 100, 2, 2, 2, 3, 0]
        rows["eligible_seasons"] = [100, 100, 3, 3, 4, 1, 0]
        rows["direction_consistency"] = [1., 1., .5, .9, .1, .1, .1]
        rows["ranking_abs_shrunk_effect"] = [100, 100, 10, 1, 1, 1, 0]
        self.assertEqual(rank_patterns(rows).label.tolist(), list("GFEDCBA"))
        tied = rows.iloc[[2, 3]].copy()
        tied["direction_consistency"] = 1.
        self.assertEqual(rank_patterns(tied).label.tolist(), ["C", "D"])

    def test_inputs_and_v2_results_unchanged(self):
        mb, tb = self.m.copy(deep=True), self.t.copy(deep=True)
        before = analyze_patterns_v2(self.m, self.t)
        match_patterns(self.m, self.t, FIXTURE)
        after = analyze_patterns_v2(self.m, self.t)
        for attr in ("seasonal", "stability", "walk_forward", "oos_summary"):
            pd.testing.assert_frame_equal(getattr(before, attr), getattr(after, attr))
        pd.testing.assert_frame_equal(self.m, mb); pd.testing.assert_frame_equal(self.t, tb)

    def test_missing_time_only_disables_daypart(self):
        result = match_patterns(self.m, self.t, dict(FIXTURE, kickoff_time=None))
        self.assertEqual(len(result.patterns), 9)
        self.assertTrue(result.patterns.pattern_type.str.endswith("weekday").all())

    def test_invalid_fixture_is_rejected(self):
        for change in (dict(match_date="bad"), dict(kickoff_time="25:00"),
                       dict(home_team="Beta"), dict(season="2020-21")):
            with self.assertRaises(ValueError):
                match_patterns(self.m, self.t, dict(FIXTURE, **change))

    def test_unknown_subjects_and_empty_history(self):
        result = match_patterns(self.m, self.t, dict(FIXTURE, home_team="Unknown1", away_team="Unknown2", referee=None))
        self.assertTrue(result.patterns.empty)
        empty = match_patterns(self.m.iloc[:0], self.t.iloc[:0], FIXTURE)
        self.assertTrue(empty.patterns.empty)


if __name__ == "__main__":
    unittest.main()
