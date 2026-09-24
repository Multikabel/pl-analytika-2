"""Presentation and read-only match-page context regressions."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "app"))
from pattern_views import (LABELS, EMPTY_MESSAGE, pattern_card, pattern_sections,
                           prematch_context, match_view, render_patterns)
from test_pattern_matcher import history, FIXTURE


def row(**kwargs):
    return dict(dict(subject="Arsenal", role="home", venue="H", weekday="Saturday",
                     daypart="", metric="yellow_cards", direction="down",
                     eligible_seasons=4, oos_tests=2, oos_hits=2,
                     current_status="pending", evidence_level="strong_candidate"), **kwargs)


class PatternViewsTests(unittest.TestCase):
    def test_labels(self):
        for key, label in zip(LABELS, ("Silný vzorec", "Zajímavý vzorec", "Slabý vzorec", "Nejasný vzorec")):
            self.assertEqual(pattern_card(row(evidence_level=key))["label"], label)

    def test_directions_and_all_metrics(self):
        for direction, word in (("up", "více"), ("down", "méně")):
            for metric, label in (("fouls", "faulů"), ("corners", "rohů"), ("yellow_cards", "žlutých karet")):
                card = pattern_card(row(direction=direction, metric=metric))
                self.assertEqual(card["title"], f"Arsenal · {word} {label}")

    def test_home_weekday_and_complement(self):
        text = pattern_card(row())["text"]
        self.assertIn("V sobotních domácích zápasech", text)
        self.assertIn("ostatních domácích zápasech v téže sezoně", text)
        self.assertIn("2 úspěšných z 2", text)

    def test_away_daypart(self):
        text = pattern_card(row(role="away", venue="A", weekday="", daypart="afternoon"))["text"]
        self.assertIn("Ve venkovních odpoledních zápasech", text)
        self.assertIn("ostatních venkovních", text)

    def test_referee_totals_and_own_baseline(self):
        text = pattern_card(row(subject="M Oliver", role="referee", venue=""))["text"]
        self.assertIn("celkový počet žlutých karet obou týmů", text)
        self.assertIn("ostatních zápasech stejného rozhodčího v téže sezoně", text)

    def test_mixed_never_claims_unanimity(self):
        card = pattern_card(row(direction="mixed", evidence_level="mixed", oos_hits=1))
        self.assertIn("nejasný směr", card["title"])
        self.assertNotIn("byl směr shodný", card["text"])

    def test_partition_keeps_matcher_order_and_no_input_mutation(self):
        frame = pd.DataFrame([row(subject=str(i), evidence_level=level)
                              for i, level in enumerate(("supported", "weak", "strong_candidate", "mixed"))])
        before = frame.copy(deep=True)
        result = pattern_sections(frame)
        self.assertEqual([x["title"][0] for x in result["main"]], ["0", "2"])
        self.assertEqual([x["title"][0] for x in result["extra"]], ["1", "3"])
        pd.testing.assert_frame_equal(frame, before)

    def test_missing_or_different_referee_hidden(self):
        frame = pd.DataFrame([row(subject="M Oliver", role="referee")])
        for ref in (None, "A Taylor"):
            self.assertEqual(pattern_sections(frame, ref)["main"], [])
        self.assertEqual(len(pattern_sections(frame, "M Oliver")["main"]), 1)

    def test_empty_and_weak_only_message_rendering(self):
        for frame in (pd.DataFrame(), pd.DataFrame([row(evidence_level="weak")])):
            result = pattern_sections(frame)
            self.assertEqual(result["empty_message"], EMPTY_MESSAGE)
            ui = MagicMock()
            render_patterns(ui, result)
            ui.info.assert_called_once_with(EMPTY_MESSAGE)
            if len(frame):
                ui.expander.assert_called_once_with("Další vzorce")

    def test_actual_matcher_integration_missing_referee(self):
        matches, stats = history()
        before_m, before_s = matches.copy(deep=True), stats.copy(deep=True)
        result = match_view(matches, stats, dict(FIXTURE, referee=None))
        self.assertTrue(result["main"])
        self.assertFalse(any("Oliver" in x["title"] for x in result["main"] + result["extra"]))
        pd.testing.assert_frame_equal(matches, before_m)
        pd.testing.assert_frame_equal(stats, before_s)

    def test_context_exact_fixture_and_appointment_only(self):
        schedule = pd.DataFrame([dict(FIXTURE, match_round=6)])
        officials = pd.DataFrame([dict(home_team="Alpha", away_team="Beta", match_round=6, referee="M Oliver")])
        args = ("Alpha", "Beta", "2026-27", "2026-10-10", pd.Timestamp("2026-10-01", tz="UTC"))
        result = prematch_context(schedule, officials, *args)
        self.assertEqual(result["referee"], "M Oliver")
        self.assertIsNone(prematch_context(schedule, pd.concat([officials, officials]), *args)["referee"])
        self.assertIsNone(prematch_context(schedule, officials.assign(match_round=7), *args)["referee"])
        self.assertIsNone(prematch_context(pd.concat([schedule, schedule]), officials, *args))

    def test_started_fixture_has_no_prematch_view(self):
        schedule = pd.DataFrame([dict(FIXTURE, match_round=6)])
        result = prematch_context(schedule, pd.DataFrame(), "Alpha", "Beta", "2026-27", "2026-10-10",
                                  pd.Timestamp("2026-10-10T16:30:00Z"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
