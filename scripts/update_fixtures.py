from pathlib import Path
import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BASE / "data" / "fixtures"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

# Primary machine-readable schedule source.
JSON_FEED = "https://fixturedownload.com/feed/json/epl-2026"

TEAM_MAP = {
    "AFC Bournemouth": "Bournemouth",
    "Bournemouth": "Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Coventry City": "Coventry",
    "Coventry": "Coventry",
    "Hull City": "Hull",
    "Hull": "Hull",
    "Ipswich Town": "Ipswich",
    "Ipswich": "Ipswich",
    "Leeds United": "Leeds",
    "Leeds": "Leeds",
    "Man City": "Manchester City",
    "Manchester City": "Manchester City",
    "Man Utd": "Manchester United",
    "Manchester United": "Manchester United",
    "Newcastle": "Newcastle United",
    "Newcastle United": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Spurs": "Tottenham",
    "Tottenham Hotspur": "Tottenham",
    "Tottenham": "Tottenham",
}

def canonical(name):
    name = str(name).strip()
    return TEAM_MAP.get(name, name)

def output_path(season):
    return FIXTURE_DIR / f"premier_league_{season}.csv"

def validate(df, season):
    required = {"match_round","match_date","home_team","away_team"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Fixture schedule missing columns: {sorted(missing)}")

    if len(df) != 380:
        raise ValueError(f"Expected 380 fixtures, got {len(df)}.")

    if df.duplicated(["home_team","away_team"]).any():
        raise ValueError("Duplicate home-away fixture detected.")

    counts = df.groupby("match_round").size()
    if len(counts) != 38 or not (counts == 10).all():
        raise ValueError(
            f"Expected 38 rounds x 10 fixtures; got {counts.to_dict()}."
        )

    teams = set(df["home_team"]) | set(df["away_team"])
    if len(teams) != 20:
        raise ValueError(f"Expected 20 teams, got {len(teams)}: {sorted(teams)}")

    if not df["match_round"].between(1,38).all():
        raise ValueError("Invalid match round outside 1..38.")

    return True

def parse_json_feed(data, season):
    rows = []
    for item in data:
        dt = pd.to_datetime(item.get("DateUtc"), utc=True, errors="coerce")
        if pd.isna(dt):
            raise ValueError(f"Invalid DateUtc: {item.get('DateUtc')}")

        # Store date/time in Europe/London because PL fixture times are UK-local.
        local = dt.tz_convert("Europe/London")

        rows.append({
            "match_round": int(item["RoundNumber"]),
            "match_date": local.strftime("%Y-%m-%d"),
            "kickoff_time": local.strftime("%H:%M"),
            "home_team": canonical(item["HomeTeam"]),
            "away_team": canonical(item["AwayTeam"]),
            "season": season,
            "source": "fixturedownload.com JSON feed",
            "source_match_number": item.get("MatchNumber"),
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    df = pd.DataFrame(rows)
    # Round order first, then actual kickoff within the round.
    df = df.sort_values(
        ["match_round","match_date","kickoff_time","source_match_number"],
        kind="stable"
    ).reset_index(drop=True)

    validate(df, season)
    return df

def sync_fixtures(season="2026-27", force=False):
    path = output_path(season)

    if path.exists() and not force:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=12):
            cached = pd.read_csv(path)
            try:
                validate(cached, season)
                return cached
            except Exception:
                pass

    headers = {
        "User-Agent": "Mozilla/5.0 PL-Analytika/2.0",
        "Accept": "application/json",
    }

    try:
        r = requests.get(JSON_FEED, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise ValueError("JSON fixture feed did not return a list.")
        df = parse_json_feed(data, season)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return df
    except Exception:
        # Never destroy a previously valid schedule because of a temporary feed issue.
        if path.exists():
            cached = pd.read_csv(path)
            try:
                validate(cached, season)
                return cached
            except Exception:
                pass
        raise

def load_fixtures(season="2026-27", auto_sync=True):
    path = output_path(season)
    if auto_sync:
        return sync_fixtures(season)

    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    validate(df, season)
    return df

def current_round(schedule, completed_matches=None, today=None):
    x = schedule.copy()

    completed = set()
    if completed_matches is not None and len(completed_matches):
        for _, r in completed_matches.iterrows():
            completed.add((str(r["home_team"]), str(r["away_team"])))

    x["played"] = [
        (str(r.home_team), str(r.away_team)) in completed
        for r in x.itertuples()
    ]

    incomplete = x.groupby("match_round")["played"].all()
    candidates = incomplete[~incomplete].index.tolist()
    rnd = int(min(candidates)) if candidates else int(x["match_round"].max())

    return rnd, x[x["match_round"] == rnd].copy()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--season", default="2026-27")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    df = sync_fixtures(args.season, force=args.force)
    print(f"{args.season}: {len(df)} validated fixtures")
    print(f"Rounds: {df.match_round.nunique()} x 10")
    print(f"Teams: {len(set(df.home_team) | set(df.away_team))}")
    print(output_path(args.season))

if __name__ == "__main__":
    main()
