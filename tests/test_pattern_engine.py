"""Synthetic-only tests for the independent descriptive Pattern Engine."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pattern_engine import (analyze_patterns, daypart, sample_class, season_patterns,
                            stability_summary, prepare_results, analyze_patterns_v2,
                            effect_reliability, walk_forward_validation, oos_summary,
                            KEY, SEASON_COLUMNS)


def inputs(specs):
    matches, teams = [], []
    for i, spec in enumerate(specs):
        season, category, value, venue, ref = spec
        home, away = ("A", f"Other{i}") if venue == "H" else (f"Other{i}", "A")
        d = date(2025, 1, 4) + timedelta(days=7 * i + (category != "Saturday"))
        matches.append(dict(match_id=str(i), season=season, match_date=d.isoformat(),
                            kickoff_time="17:30" if category == "Saturday" else "15:00",
                            home_team=home, away_team=away, referee=ref))
        for team, opponent, side in ((home, away, "H"), (away, home, "A")):
            v = value if team == "A" else 1
            teams.append(dict(match_id=str(i), season=season, team=team, opponent=opponent,
                              venue=side, fouls_committed=v, yellow_cards=v, corners_for=v))
    return pd.DataFrame(matches), pd.DataFrame(teams)


def specs(season="S1", group=5, baseline=2, high=4, low=2, venue="H", ref="M Oliver"):
    return [(season, "Saturday", high, venue, ref)] * group + [(season, "Sunday", low, venue, ref)] * baseline


def select(result, kind="team_weekday", season="S1", entity="A", metric="fouls"):
    x = result.seasonal
    category = x.weekday.eq("Saturday") if kind.endswith("weekday") else x.daypart.eq("late")
    return x.loc[x.pattern_type.eq(kind) & x.season.eq(season) & x.entity.eq(entity)
                 & x.venue.eq("H" if kind.startswith("team") else "")
                 & x.metric.eq(metric) & category].iloc[0]


class PatternEngineTests(unittest.TestCase):
    def test_daypart_boundaries(self):
        for value, expected in (("14:59", "early"), ("15:00", "afternoon"),
                                ("17:29", "afternoon"), ("17:30", "late")):
            self.assertEqual(daypart(value), expected)

    def test_invalid_times_are_not_categories(self):
        for value in (None, np.nan, "", "24:00", "15:60", "3:00", "15:00Z"):
            self.assertIsNone(daypart(value))

    def test_sample_thresholds(self):
        for n, expected in ((0, "insufficient"), (1, "insufficient"), (2, "insufficient"),
                            (3, "very_small"), (4, "very_small"), (5, "small"),
                            (7, "small"), (8, "usable"), (20, "usable")):
            self.assertEqual(sample_class(n), expected)

    def test_team_baseline_preserves_venue(self):
        result = analyze_patterns(*inputs(specs() + specs(venue="A", high=100, low=80)))
        row = select(result)
        self.assertEqual((row.N_group, row.N_baseline), (5, 2))
        self.assertEqual((row.group_mean, row.baseline_mean, row.effect), (4, 2, 2))
        away = result.seasonal.query("entity == 'A' and venue == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((away.group_mean, away.baseline_mean), (100, 80))

    def test_referee_baseline_uses_own_match_totals(self):
        result = analyze_patterns(*inputs(specs() + specs(ref="Other Ref", high=100)))
        for metric in ("fouls", "yellow_cards", "corners"):
            row = select(result, "referee_weekday", entity="M Oliver", metric=metric)
            self.assertEqual((row.group_mean, row.baseline_mean, row.effect), (5, 3, 2))
            self.assertEqual((row.N_group, row.N_baseline), (5, 2))

    def test_daypart_uses_complement(self):
        result = analyze_patterns(*inputs(specs()))
        self.assertEqual(select(result, "team_daypart").effect, 2)
        self.assertEqual(select(result, "referee_daypart", entity="M Oliver").effect, 2)

    def test_weekday_is_derived_from_date(self):
        team, _, _ = prepare_results(*inputs(specs()))
        self.assertEqual(set(team.weekday), {"Saturday", "Sunday"})

    def test_seasons_never_pool_absolute_values(self):
        result = analyze_patterns(*inputs(specs() + specs("S2", high=104, low=102)))
        self.assertEqual(select(result).baseline_mean, 2)
        self.assertEqual(select(result, season="S2").baseline_mean, 102)
        self.assertFalse(any("mean" in column for column in result.stability.columns))

    def test_stability_three_of_three_up(self):
        result = analyze_patterns(*inputs(sum((specs(s) for s in ("S1", "S2", "S3")), [])))
        row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((row.eligible_seasons, row.positive_seasons, row.direction,
                          row.direction_consistency), (3, 3, "up", 1.))

    def test_mixed_direction(self):
        result = analyze_patterns(*inputs(specs() + specs("S2", high=1, low=3)))
        row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((row.positive_seasons, row.negative_seasons, row.direction,
                          row.direction_consistency), (1, 1, "mixed", .5))

    def test_negative_and_exact_zero(self):
        for high, direction in ((1, "down"), (2, "neutral")):
            result = analyze_patterns(*inputs(specs(high=high)))
            row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
            self.assertEqual(row.direction, direction)
            self.assertEqual(row.neutral_seasons, int(high == 2))

    def test_zero_plus_positive_is_mixed(self):
        result = analyze_patterns(*inputs(specs() + specs("S2", high=2)))
        row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((row.direction, row.positive_seasons, row.neutral_seasons), ("mixed", 1, 1))

    def test_small_samples_excluded_from_stability(self):
        result = analyze_patterns(*inputs(specs(group=4) + specs("S2", group=2)))
        row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((row.eligible_seasons, row.direction), (0, "insufficient"))
        self.assertTrue(pd.isna(row.direction_consistency))

    def test_zero_baseline_has_missing_relative_effect(self):
        row = select(analyze_patterns(*inputs(specs(low=0))))
        self.assertEqual(row.effect, 4)
        self.assertTrue(pd.isna(row.relative_effect))

    def test_no_complement_is_not_evaluable(self):
        result = analyze_patterns(*inputs(specs(baseline=0)))
        row = select(result)
        self.assertEqual(row.N_baseline, 0)
        self.assertFalse(row.evaluable)
        self.assertTrue(pd.isna(row.effect))
        self.assertTrue(result.stability.eligible_seasons.eq(0).all())

    def test_full_precision(self):
        rows = specs(group=3, high=1, low=3)
        rows[0] = ("S1", "Saturday", 2, "H", "M Oliver")
        row = select(analyze_patterns(*inputs(rows)))
        self.assertEqual(row.group_mean, 4 / 3)
        self.assertEqual(row.relative_effect, (4 / 3 - 3) / 3)

    def test_similar_referees_remain_independent(self):
        names = ["K Kavanagh", "C Kavanagh", "O Oliver", "M Oliver",
                 "J Smith", "L Smith", "R Madley", "A Madley"]
        result = analyze_patterns(*inputs(sum((specs(ref=n, group=1, baseline=0) for n in names), [])))
        refs = result.seasonal[result.seasonal.pattern_type.str.startswith("referee")]
        self.assertEqual(set(refs.entity), set(names))
        self.assertTrue(refs.sparse_identity.all())

    def test_missing_metric_is_not_zero_or_partial_total(self):
        m, t = inputs(specs())
        t.loc[0, "corners_for"] = np.nan
        result = analyze_patterns(m, t)
        self.assertEqual(select(result, metric="corners").N_group, 4)
        self.assertEqual(select(result, "referee_weekday", entity="M Oliver", metric="corners").N_group, 4)
        self.assertEqual(result.quality["missing_or_invalid_team_values"]["corners"], 1)

    def test_bad_date_time_and_missing_ref_are_reported(self):
        m, t = inputs(specs())
        m.loc[0, "kickoff_time"] = "bad"
        m.loc[1, "match_date"] = "bad"
        m.loc[2, "referee"] = ""
        result = analyze_patterns(m, t)
        self.assertEqual(result.quality["invalid_dates"], 1)
        self.assertEqual(result.quality["invalid_kickoff_times"], 1)
        self.assertEqual(result.quality["missing_referees"], 1)
        self.assertEqual(select(result).N_group, 4)

    def test_conflicting_duplicate_or_missing_pair_raises(self):
        m, t = inputs(specs())
        for bad_m, bad_t in ((pd.concat([m, m.iloc[:1]]), t), (m, t.iloc[1:]),
                             (m, pd.concat([t, t.iloc[:1]]))):
            with self.assertRaises(ValueError):
                analyze_patterns(bad_m, bad_t)
        bad = t.copy(); bad.loc[0, "opponent"] = "wrong"
        with self.assertRaises(ValueError):
            analyze_patterns(m, bad)

    def test_inputs_unchanged_and_empty_supported(self):
        m, t = inputs(specs()); mb, tb = m.copy(deep=True), t.copy(deep=True)
        analyze_patterns(m, t)
        pd.testing.assert_frame_equal(m, mb); pd.testing.assert_frame_equal(t, tb)
        result = analyze_patterns(m.iloc[:0], t.iloc[:0])
        self.assertTrue(result.seasonal.empty and result.stability.empty)

    def test_duplicate_season_summary_rejected(self):
        result = analyze_patterns(*inputs(specs()))
        with self.assertRaises(ValueError):
            stability_summary(pd.concat([result.seasonal, result.seasonal]))

    def test_invalid_numeric_values_are_missing(self):
        m, t = inputs(specs())
        t["corners_for"] = t.corners_for.astype(float)
        for index, value in ((0, -1), (2, np.inf), (4, 1.5)):
            t.loc[index, "corners_for"] = value
        result = analyze_patterns(m, t)
        self.assertEqual(result.quality["missing_or_invalid_team_values"]["corners"], 3)
        self.assertEqual(select(result, metric="corners").N_group, 2)

    def test_nullable_missing_counts_are_reported(self):
        m, t = inputs(specs())
        t["corners_for"] = t.corners_for.astype("Int64")
        t.loc[0, "corners_for"] = pd.NA
        result = analyze_patterns(m, t)
        self.assertEqual(result.quality["missing_or_invalid_team_values"]["corners"], 1)

    def test_unknown_category_does_not_enter_complement(self):
        m, t = inputs(specs())
        m.loc[5:, "kickoff_time"] = "bad"
        result = analyze_patterns(m, t)
        self.assertEqual(select(result, "team_daypart").N_baseline, 0)
        self.assertEqual(select(result).N_baseline, 2)

    def test_eligibility_boundary_five_and_missing_baseline(self):
        result = analyze_patterns(*inputs(specs(group=5) + specs("S2", group=4)
                                           + specs("S3", group=8, baseline=0)))
        row = result.stability.query("entity == 'A' and weekday == 'Saturday'").iloc[0]
        self.assertEqual((row.eligible_seasons, row.direction), (1, "up"))


def validation_seasons(effects, counts=None, baselines=None, seasons=None):
    rows = []
    for i, effect in enumerate(effects):
        ng = counts[i] if counts is not None else 5
        nb = baselines[i] if baselines is not None else 10
        rows.append(dict(season=seasons[i] if seasons else f"{2022+i}-{str(2023+i)[-2:]}",
                         pattern_type="team_weekday", entity="A", venue="H", weekday="Saturday",
                         daypart="", metric="fouls", N_group=ng, N_baseline=nb,
                         group_mean=10 + effect, baseline_mean=10, effect=effect,
                         relative_effect=effect / 10, sample_class=sample_class(ng),
                         evaluable=bool(ng and nb), sparse_identity=False))
    return pd.DataFrame(rows, columns=SEASON_COLUMNS)


class PatternEngineV2Tests(unittest.TestCase):
    def test_no_target_or_future_lookahead(self):
        original = validation_seasons([1, 2, 3, -99])
        first = walk_forward_validation(original).iloc[2]
        changed = original.copy()
        changed.loc[2, "effect"] = -1000
        changed.loc[3, "effect"] = 1000
        second = walk_forward_validation(changed).iloc[2]
        for field in ("historical_seasons_used", "historical_eligible_count", "expected_direction"):
            self.assertEqual(first[field], second[field])
        self.assertEqual(first.historical_seasons_used, ("2022-23", "2023-24"))
        self.assertEqual((first.validation_result, second.validation_result), ("hit", "miss"))
        short = walk_forward_validation(original.iloc[:3])
        pd.testing.assert_frame_equal(short, walk_forward_validation(original).iloc[:3])

    def test_minimum_two_history_seasons(self):
        rows = walk_forward_validation(validation_seasons([1, 1, 1]))
        self.assertEqual(rows.validation_result.tolist(), ["not_testable", "not_testable", "hit"])
        self.assertIsNone(rows.iloc[1].expected_direction)

    def test_up_hit(self):
        self.assertEqual(walk_forward_validation(validation_seasons([1, 2, 3])).iloc[-1].validation_result, "hit")

    def test_up_miss(self):
        self.assertEqual(walk_forward_validation(validation_seasons([1, 2, -3])).iloc[-1].validation_result, "miss")

    def test_down_hit(self):
        row = walk_forward_validation(validation_seasons([-1, -2, -3])).iloc[-1]
        self.assertEqual((row.expected_direction, row.validation_result), ("down", "hit"))

    def test_down_miss(self):
        self.assertEqual(walk_forward_validation(validation_seasons([-1, -2, 3])).iloc[-1].validation_result, "miss")

    def test_target_zero_is_neutral(self):
        row = walk_forward_validation(validation_seasons([1, 2, 0])).iloc[-1]
        self.assertEqual((row.expected_direction, row.validation_result), ("up", "neutral"))

    def test_mixed_history_has_no_directional_test(self):
        for effects in ([1, -1, 3], [1, 0, 3], [0, 0, 3]):
            validation = walk_forward_validation(validation_seasons(effects))
            self.assertEqual(validation.iloc[-1].expected_direction, "mixed")
            self.assertEqual(validation.iloc[-1].validation_result, "mixed")
            self.assertEqual(oos_summary(validation).iloc[0].oos_tests, 0)

    def test_small_target_pending(self):
        row = walk_forward_validation(validation_seasons([1, 1, 1], counts=[5, 5, 4])).iloc[-1]
        self.assertEqual((row.expected_direction, row.validation_result), ("up", "pending"))

    def test_target_without_baseline_pending(self):
        row = walk_forward_validation(validation_seasons([1, 1, 1], baselines=[10, 10, 0])).iloc[-1]
        self.assertEqual(row.validation_result, "pending")

    def test_small_history_excluded(self):
        row = walk_forward_validation(validation_seasons([-1, 1, 1], counts=[4, 5, 5])).iloc[-1]
        self.assertEqual(row.historical_seasons_used, ("2023-24",))
        self.assertEqual(row.validation_result, "not_testable")

    def test_missing_baseline_history_excluded(self):
        row = walk_forward_validation(validation_seasons([-1, 1, 1], baselines=[0, 10, 10])).iloc[-1]
        self.assertEqual(row.historical_eligible_count, 1)

    def test_numeric_season_order_and_gaps(self):
        table = validation_seasons([1, 1, 1], seasons=["2025/26", "2022-23", "2024-2025"])
        result = walk_forward_validation(table)
        self.assertEqual(result.target_season.tolist(), ["2022-23", "2024-2025", "2025/26"])
        self.assertEqual(result.iloc[-1].historical_seasons_used, ("2022-23", "2024-2025"))

    def test_invalid_and_duplicate_seasons_rejected(self):
        for seasons in (["2022-23", "2022/23"], ["S1", "S2"], ["2022-24", "2023-24"]):
            with self.assertRaises(ValueError):
                walk_forward_validation(validation_seasons([1, 1], seasons=seasons))

    def test_oos_counts_only_directional_tests(self):
        validation = walk_forward_validation(validation_seasons([1, 1, 1, 1, -1, 1],
                                                                  counts=[5, 5, 3, 5, 5, 5]))
        self.assertEqual(validation.validation_result.tolist(),
                         ["not_testable", "not_testable", "pending", "hit", "miss", "mixed"])
        row = oos_summary(validation).iloc[0]
        self.assertEqual((row.oos_tests, row.oos_hits, row.oos_misses, row.oos_neutral, row.oos_hit_rate),
                         (2, 1, 1, 0, .5))

    def test_one_of_one_remains_explicit(self):
        row = oos_summary(walk_forward_validation(validation_seasons([1, 1, 1]))).iloc[0]
        self.assertEqual((row.oos_tests, row.oos_hits, row.oos_hit_rate), (1, 1, 1.))

    def test_neutral_counts_in_denominator(self):
        row = oos_summary(walk_forward_validation(validation_seasons([1, 1, 1, 0]))).iloc[0]
        self.assertEqual((row.oos_tests, row.oos_hits, row.oos_neutral, row.oos_hit_rate), (2, 1, 1, .5))

    def test_se_and_ci(self):
        result = effect_reliability(pd.Series([1., 3., 5.]), pd.Series([2., 4., 6., 8.]), -2.)
        self.assertAlmostEqual(result["effect_se"], np.sqrt(3))
        self.assertAlmostEqual(result["ci_low"], -2 - 1.96 * np.sqrt(3))
        self.assertAlmostEqual(result["ci_high"], -2 + 1.96 * np.sqrt(3))
        self.assertEqual(result["uncertainty_status"], "available")

    def test_small_n_has_missing_uncertainty(self):
        for group, baseline in (([1], [2, 3]), ([1, 2], [3]), ([], [2, 3])):
            result = effect_reliability(pd.Series(group, dtype=float), pd.Series(baseline), 1.)
            self.assertTrue(pd.isna(result["effect_se"]))
            self.assertEqual(result["uncertainty_status"], "insufficient_n")

    def test_zero_or_missing_variance_is_not_certainty(self):
        for group in ([2., 2.], [np.nan, np.nan]):
            result = effect_reliability(pd.Series(group), pd.Series([1., 3.]), 0.)
            self.assertTrue(pd.isna(result["effect_se"]))
            self.assertTrue(pd.isna(result["ci_low"]))
            self.assertTrue(pd.isna(result["ci_high"]))

    def test_shrinkage_formula_monotonicity_and_bounds(self):
        previous = -1
        for n in (1, 2, 5, 15, 100):
            result = effect_reliability(pd.Series(range(n)), pd.Series(range(n)), -3.)
            weight = result["reliability_weight"]
            self.assertAlmostEqual(weight, (n / 2) / (n / 2 + 5))
            self.assertGreaterEqual(weight, previous)
            self.assertGreaterEqual(weight, 0)
            self.assertLessEqual(weight, 1)
            self.assertLessEqual(abs(result["shrunk_effect"]), 3.)
            previous = weight

    def test_small_baseline_limits_weight(self):
        a = effect_reliability(pd.Series(range(15)), pd.Series(range(2)), 3.)
        b = effect_reliability(pd.Series(range(15)), pd.Series(range(15)), 3.)
        self.assertLess(a["reliability_weight"], b["reliability_weight"])

    def test_zero_effect_stays_zero(self):
        result = effect_reliability(pd.Series([1., 3., 5.]), pd.Series([1., 3., 5.]), 0.)
        self.assertEqual(result["shrunk_effect"], 0.)

    def test_v1_results_and_inputs_unchanged(self):
        m, t = inputs(specs("2022-23") + specs("2023-24") + specs("2024-25"))
        mb, tb = m.copy(deep=True), t.copy(deep=True)
        v1, v2 = analyze_patterns(m, t), analyze_patterns_v2(m, t)
        pd.testing.assert_frame_equal(v1.seasonal, v2.seasonal[SEASON_COLUMNS])
        pd.testing.assert_frame_equal(v1.stability, v2.stability)
        self.assertEqual(v1.quality, v2.quality)
        pd.testing.assert_frame_equal(m, mb); pd.testing.assert_frame_equal(t, tb)
        known = v2.seasonal[v2.seasonal.effect.notna()]
        self.assertTrue(known.shrunk_effect.abs().le(known.effect.abs()).all())
        self.assertTrue(v2.seasonal.loc[v2.seasonal.effect.isna(), "shrunk_effect"].isna().all())

    def test_pattern_identities_are_separate_in_validation(self):
        first = validation_seasons([1, 1, 1])
        other = validation_seasons([-1, -1, -1]); other["entity"] = "B"
        result = walk_forward_validation(pd.concat([first, other]))
        self.assertEqual(result.query("entity == 'A'").iloc[-1].expected_direction, "up")
        self.assertEqual(result.query("entity == 'B'").iloc[-1].expected_direction, "down")

    def test_empty_v2_result(self):
        m, t = inputs(specs())
        result = analyze_patterns_v2(m.iloc[:0], t.iloc[:0])
        self.assertTrue(result.walk_forward.empty and result.oos_summary.empty)


if __name__ == "__main__":
    unittest.main()
