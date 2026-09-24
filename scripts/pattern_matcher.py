"""Pre-match descriptive context, using only results before the fixture's day.

No IO or prediction adjustments. Never accept unbounded aggregate v2 results.
"""
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from pattern_engine import (KEY, WEEKDAYS, _season_start, daypart,
                            prepare_results, season_patterns, stability_summary,
                            walk_forward_validation, oos_summary)


EVIDENCE_ORDER = {"strong_candidate": 0, "supported": 1, "weak": 2, "mixed": 3}
MATCH_COLUMNS = [*KEY, "subject", "role", "matched_context", "direction",
                 "direction_consistency", "eligible_seasons", "historical_eligible_seasons",
                 "season_effects", "current_season", "current_status", "current_sample_class",
                 "current_N_group", "current_N_baseline", "oos_tests", "oos_hits",
                 "oos_misses", "oos_neutral", "oos_hit_rate", "oos_history",
                 "evidence_level", "evidence_reason", "ranking_abs_shrunk_effect"]


@dataclass
class MatchPatterns:
    patterns: pd.DataFrame
    context: dict
    quality: dict


def evidence_level(direction, historical_eligible_seasons, tests, hits, misses, neutral):
    """Fixed symmetric categories, not a betting recommendation or fitted score."""
    if direction == "mixed":
        return "mixed", "Eligible season directions are not unanimous (v1 mixed)."
    directional = direction in ("up", "down")
    all_hits = tests > 0 and hits == tests and misses == 0 and neutral == 0
    if directional and historical_eligible_seasons >= 3 and tests >= 2 and all_hits:
        return "strong_candidate", "Unanimous direction; >=3 prior eligible seasons; >=2 OOS tests, all hit."
    if directional and historical_eligible_seasons >= 2 and tests >= 1 and all_hits:
        return "supported", "Unanimous direction; >=2 prior eligible seasons; >=1 OOS test, all hit."
    return "weak", "No unanimous directional evidence meeting the fixed historical/OOS minimums."


def rank_patterns(patterns):
    """Deterministic lexicographic ranking; retain every matched pattern."""
    if patterns.empty:
        return patterns.copy()
    ranked = patterns.assign(_evidence_order=patterns.evidence_level.map(EVIDENCE_ORDER))
    return ranked.sort_values(
        ["_evidence_order", "oos_tests", "eligible_seasons", "direction_consistency",
         "ranking_abs_shrunk_effect", *KEY],
        ascending=[True, False, False, False, False, *([True] * len(KEY))],
        na_position="last", kind="stable"
    ).drop(columns="_evidence_order").reset_index(drop=True)


def _context(fixture):
    for field in ("home_team", "away_team", "season", "match_date"):
        if not isinstance(fixture.get(field), str) or not fixture[field].strip():
            raise ValueError(f"Missing fixture {field}")
    if fixture["home_team"] == fixture["away_team"]:
        raise ValueError("Home and away team must differ")
    value = fixture["match_date"]
    date = pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
    if date.strftime("%Y-%m-%d") != value:
        raise ValueError("Fixture date must be YYYY-MM-DD")
    year = _season_start(fixture["season"])
    if not pd.Timestamp(year, 7, 1) <= date < pd.Timestamp(year + 1, 7, 1):
        raise ValueError("Fixture date outside season")
    kickoff = fixture.get("kickoff_time")
    if kickoff is None or pd.isna(kickoff) or kickoff == "":
        kickoff, part = None, None
    else:
        part = daypart(kickoff)
        if part is None:
            raise ValueError("Invalid fixture kickoff HH:MM")
    referee = fixture.get("referee")
    if referee is None or pd.isna(referee) or (isinstance(referee, str) and not referee.strip()):
        referee = None
    elif not isinstance(referee, str):
        raise ValueError("Referee must be an exact stored identity or missing")
    return dict(home_team=fixture["home_team"], away_team=fixture["away_team"],
                season=fixture["season"], match_date=value, kickoff_time=kickoff,
                weekday=WEEKDAYS[date.dayofweek], daypart=part, referee=referee)


def match_patterns(matches, team_stats, fixture):
    """Match all four existing families to known context, never target outcomes.

    Excludes the entire target calendar day (including earlier kickoffs).
    Fixture fields must be supplied as known pre-match; no referee/result lookup
    from the target row is performed. No caller frame or v2 result is mutated.
    """
    context = _context(fixture)
    cutoff = pd.Timestamp(context["match_date"])
    year = _season_start(context["season"])
    dates = pd.to_datetime(matches.match_date, format="%Y-%m-%d", errors="coerce")
    history = matches.loc[dates.lt(cutoff)].copy()
    starts = history.season.map(_season_start)
    target_identity = (starts.eq(year) & history.home_team.eq(context["home_team"])
                       & history.away_team.eq(context["away_team"]))
    history = history.loc[starts.le(year) & ~target_identity].sort_values("match_id").copy()
    # Unknown dates cannot establish pre-match availability and are excluded.
    stats = team_stats.loc[team_stats.match_id.isin(history.match_id)].sort_values(["match_id", "venue"]).copy()
    team, ref, quality = prepare_results(history, stats)
    quality = {**quality, "cutoff_exclusive": context["match_date"],
               "availability_policy": "previous_calendar_days_only"}
    # Filter entities/venues only. Keep ALL categories for season-local complements.
    team = team.loc[(team.entity.eq(context["home_team"]) & team.venue.eq("H"))
                    | (team.entity.eq(context["away_team"]) & team.venue.eq("A"))]
    ref = ref.loc[ref.entity.eq(context["referee"])] if context["referee"] else ref.iloc[:0]
    parts = [season_patterns(team, "team", include_reliability=True),
             season_patterns(ref, "referee", include_reliability=True)]
    nonempty = [part for part in parts if not part.empty]
    seasonal = pd.concat(nonempty, ignore_index=True) if nonempty else parts[0]
    # Evaluate every relevant category/metric before applying any evidence rules.
    relevant = ((seasonal.pattern_type.str.endswith("weekday") & seasonal.weekday.eq(context["weekday"]))
                | (seasonal.pattern_type.str.endswith("daypart") & seasonal.daypart.eq(context["daypart"])))
    seasonal = seasonal.loc[relevant].copy()
    stability = stability_summary(seasonal)
    validation = walk_forward_validation(seasonal)
    oos = oos_summary(validation)
    records = []
    for key, rows in seasonal.groupby(KEY, sort=True, dropna=False):
        def matching(frame):
            mask = pd.Series(True, index=frame.index)
            for column, value in zip(KEY, key):
                mask &= frame[column].eq(value)
            return frame.loc[mask]
        rows = rows.assign(_year=rows.season.map(_season_start)).sort_values("_year")
        eligible = rows.N_group.ge(5) & rows.N_baseline.gt(0) & rows.effect.notna()
        historical_count = int((eligible & rows._year.lt(year)).sum())
        s, o = matching(stability).iloc[0], matching(oos).iloc[0]
        level, reason = evidence_level(s.direction, historical_count, o.oos_tests,
                                       o.oos_hits, o.oos_misses, o.oos_neutral)
        current = rows.loc[rows._year.eq(year)]
        if len(current):
            c = current.iloc[0]
            current_status = "eligible" if c.N_group >= 5 and c.N_baseline > 0 and pd.notna(c.effect) else "pending"
            sample, ng, nb = c.sample_class, int(c.N_group), int(c.N_baseline)
        else:
            # Explicitly distinguish an absent category from an absent subject history.
            family, entity, venue, weekday, part, metric = key
            frame = ref if family.startswith("referee") else team
            current_rows = frame.loc[frame.season.map(_season_start).eq(year)
                                     & frame.entity.eq(entity) & frame.venue.eq(venue)]
            factor = "weekday" if weekday else "daypart"
            known = current_rows.loc[current_rows[factor].notna()]
            ng, nb = 0, int(known[metric].notna().sum())
            current_status, sample = "pending", "insufficient"
        latest = rows.loc[eligible & rows.shrunk_effect.notna()]
        tie_break = abs(float(latest.iloc[-1].shrunk_effect)) if len(latest) else np.nan
        identity = dict(zip(KEY, key))
        role = "referee" if key[0].startswith("referee") else "home" if key[2] == "H" else "away"
        records.append(dict(identity, subject=key[1], role=role,
            matched_context={**context, "venue": key[2]}, direction=s.direction,
            direction_consistency=s.direction_consistency, eligible_seasons=int(s.eligible_seasons),
            historical_eligible_seasons=historical_count,
            season_effects=rows.drop(columns="_year").to_dict("records"),
            current_season=context["season"], current_status=current_status,
            current_sample_class=sample, current_N_group=ng, current_N_baseline=nb,
            oos_tests=int(o.oos_tests), oos_hits=int(o.oos_hits), oos_misses=int(o.oos_misses),
            oos_neutral=int(o.oos_neutral), oos_hit_rate=o.oos_hit_rate,
            oos_history=matching(validation).to_dict("records"), evidence_level=level,
            evidence_reason=reason, ranking_abs_shrunk_effect=tie_break))
    return MatchPatterns(rank_patterns(pd.DataFrame(records, columns=MATCH_COLUMNS)), context, quality)
