"""Resolve completed fixtures without confusing the two season meetings."""
import pandas as pd


def completed_fixture_rows(team_matches, season, home, away):
    """Return one complete, unambiguous home/away pair, otherwise None."""
    tm = team_matches
    home_rows = tm[
        tm.season.astype(str).eq(str(season))
        & tm.team.astype(str).eq(str(home))
        & tm.opponent.astype(str).eq(str(away))
        & tm.venue.astype(str).eq("H")
    ]
    if len(home_rows) != 1 or str(home) == str(away):
        return None
    home_row = home_rows.iloc[0]
    mid = home_row.match_id
    if pd.isna(mid) or not str(mid).strip() or pd.isna(home_row.match_date):
        return None
    rows = tm[tm.match_id.astype(str).eq(str(mid))]
    if len(rows) != 2 or not rows.season.astype(str).eq(str(season)).all():
        return None
    away_rows = rows[
        rows.team.astype(str).eq(str(away))
        & rows.opponent.astype(str).eq(str(home))
        & rows.venue.astype(str).eq("A")
    ]
    if len(away_rows) != 1:
        return None
    return rows
