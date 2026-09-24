"""Read-only, season-local descriptive associations in observed PL results.

No filesystem access, training, prediction or persistence is performed here.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


METRICS = {"fouls": "fouls_committed", "yellow_cards": "yellow_cards",
           "corners": "corners_for"}
KEY = ["pattern_type", "entity", "venue", "weekday", "daypart", "metric"]
SEASON_COLUMNS = ["season", *KEY, "N_group", "N_baseline", "group_mean",
                  "baseline_mean", "effect", "relative_effect", "sample_class",
                  "evaluable", "sparse_identity"]
STABILITY_COLUMNS = [*KEY, "eligible_seasons", "positive_seasons", "negative_seasons",
                     "neutral_seasons", "direction", "direction_consistency"]
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass
class PatternResults:
    seasonal: pd.DataFrame
    stability: pd.DataFrame
    quality: dict


def daypart(value):
    """Strict HH:MM, interpreted as already-local British time."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except ValueError:
        return None
    if not (value[:2].isdigit() and value[3:].isdigit()
            and 0 <= hour < 24 and 0 <= minute < 60):
        return None
    minutes = 60 * hour + minute
    return "early" if minutes < 900 else "afternoon" if minutes < 1050 else "late"


def sample_class(n):
    if n < 3:
        return "insufficient"
    if n < 5:
        return "very_small"
    if n < 8:
        return "small"
    return "usable"


def _required(frame, columns, label):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label}: missing columns {sorted(missing)}")


def _identity(frame, columns, label):
    for column in columns:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{label}: missing identity {column}")


def prepare_results(matches, team_stats):
    """Validate one match/two reciprocal team rows; preserve exact identities."""
    mc = ["match_id", "season", "match_date", "kickoff_time", "home_team", "away_team", "referee"]
    tc = ["match_id", "season", "team", "opponent", "venue", *METRICS.values()]
    _required(matches, mc, "matches")
    _required(team_stats, tc, "team_stats")
    m, t = matches[mc].copy(), team_stats[tc].copy()
    _identity(m, ["match_id", "season", "home_team", "away_team"], "matches")
    _identity(t, ["match_id", "season", "team", "opponent", "venue"], "team_stats")
    if m.match_id.duplicated().any() or m.duplicated(["season", "home_team", "away_team"]).any():
        raise ValueError("Ambiguous match identity")
    if (t.duplicated(["match_id", "venue"]).any() or not t.venue.isin(["H", "A"]).all()
            or set(t.match_id) != set(m.match_id)
            or not t.groupby("match_id").size().eq(2).all()):
        raise ValueError("Expected exactly two H/A rows for every match")
    x = t.merge(m, on="match_id", suffixes=("_team", ""), validate="many_to_one")
    home = x.venue.eq("H")
    if (not x.season_team.eq(x.season).all() or m.home_team.eq(m.away_team).any()
            or not x.team.eq(x.home_team.where(home, x.away_team)).all()
            or not x.opponent.eq(x.away_team.where(home, x.home_team)).all()):
        raise ValueError("Conflicting team/match identities")
    dates = pd.to_datetime(m.match_date, format="%Y-%m-%d", errors="coerce")
    m["weekday"] = dates.dt.dayofweek.map(dict(enumerate(WEEKDAYS)))
    m["daypart"] = m.kickoff_time.map(daypart)
    missing_ref = m.referee.isna() | m.referee.astype(str).str.strip().eq("")
    quality = {"matches": len(m), "invalid_dates": int(dates.isna().sum()),
               "invalid_kickoff_times": int(m.daypart.isna().sum()),
               "missing_referees": int(missing_ref.sum()), "missing_or_invalid_team_values": {}}
    for metric, column in METRICS.items():
        values = pd.to_numeric(t[column], errors="coerce")
        good = (np.isfinite(values) & values.ge(0) & values.mod(1).eq(0)).fillna(False)
        t[metric] = values.where(good)
        quality["missing_or_invalid_team_values"][metric] = int((~good).sum())
    team = t[["match_id", "team", "venue", *METRICS]].merge(
        m[["match_id", "season", "weekday", "daypart"]], on="match_id", validate="many_to_one")
    team = team.rename(columns={"team": "entity"})
    # Require both observed sides; a missing side never becomes a partial total.
    totals = t.groupby("match_id")[list(METRICS)].sum(min_count=2)
    ref = m.loc[~missing_ref, ["match_id", "season", "referee", "weekday", "daypart"]].merge(
        totals, on="match_id", validate="one_to_one").rename(columns={"referee": "entity"})
    ref["venue"] = ""
    return team, ref, quality


def season_patterns(frame, entity_type):
    """Metric-specific observed N; baseline is the same-season complement."""
    if entity_type not in ("team", "referee"):
        raise ValueError("entity_type must be team or referee")
    records = []
    for (season, entity, venue), context in frame.groupby(["season", "entity", "venue"], sort=True):
        for factor in ("weekday", "daypart"):
            known = context[context[factor].notna()]
            for category in sorted(known[factor].unique()):
                mask = known[factor].eq(category)
                for metric in METRICS:
                    group, baseline = known.loc[mask, metric].dropna(), known.loc[~mask, metric].dropna()
                    ng, nb = len(group), len(baseline)
                    gm, bm = group.mean(), baseline.mean()
                    effect = gm - bm if ng and nb else np.nan
                    records.append(dict(season=season, pattern_type=f"{entity_type}_{factor}",
                        entity=entity, venue=venue, weekday=category if factor == "weekday" else "",
                        daypart=category if factor == "daypart" else "", metric=metric,
                        N_group=ng, N_baseline=nb, group_mean=gm, baseline_mean=bm,
                        effect=effect, relative_effect=effect / bm if nb and bm != 0 else np.nan,
                        sample_class=sample_class(ng), evaluable=bool(ng and nb),
                        sparse_identity=context.match_id.nunique() < 3))
    return pd.DataFrame(records, columns=SEASON_COLUMNS)


def stability_summary(seasonal):
    """Summarize signs only, never absolute means across seasons."""
    if seasonal.duplicated(["season", *KEY]).any():
        raise ValueError("Duplicate season-pattern would inflate stability")
    records = []
    for key, rows in seasonal.groupby(KEY, sort=True, dropna=False):
        effects = rows.loc[rows.N_group.ge(5) & rows.N_baseline.gt(0)
                           & rows.effect.notna(), "effect"]
        n = len(effects)
        pos, neg, zero = int(effects.gt(0).sum()), int(effects.lt(0).sum()), int(effects.eq(0).sum())
        direction = ("insufficient" if not n else "up" if pos == n else
                     "down" if neg == n else "neutral" if zero == n else "mixed")
        records.append(dict(zip(KEY, key), eligible_seasons=n, positive_seasons=pos,
                            negative_seasons=neg, neutral_seasons=zero, direction=direction,
                            direction_consistency=max(pos, neg, zero) / n if n else np.nan))
    return pd.DataFrame(records, columns=STABILITY_COLUMNS)


def analyze_patterns(matches, team_stats):
    team, referee, quality = prepare_results(matches, team_stats)
    seasonal = pd.concat([season_patterns(team, "team"), season_patterns(referee, "referee")],
                         ignore_index=True)
    return PatternResults(seasonal, stability_summary(seasonal), quality)
