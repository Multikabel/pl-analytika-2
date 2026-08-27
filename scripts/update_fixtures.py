from pathlib import Path
import argparse
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BASE / "data" / "fixtures"
RAW_DIR = BASE / "data" / "raw"
TABLES = BASE / "data" / "tables"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

OFFICIAL_URLS = {
    "2026-27": "https://www.premierleague.com/en/news/4675097",
}

TEAM_MAP = {
    "AFC Bournemouth": "Bournemouth",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    "Manchester Utd": "Manchester United",
    "Man Utd": "Manchester United",
    "Man City": "Manchester City",
    "Newcastle": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Tottenham Hotspur": "Tottenham",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    "Brighton": "Brighton & Hove Albion",
}

MONTHS = {
    "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
    "July":7,"August":8,"September":9,"October":10,"November":11,"December":12
}

DAY_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?$"
)

FIX_RE = re.compile(
    r"^(?:(\d{1,2}:\d{2})\s+)?(.+?)\s+v\s+(.+?)(?:\s+\([^)]*\))?(?:\*+)?$"
)

def canonical(name):
    name = re.sub(r"^\*+|\*+$", "", str(name)).strip()
    return TEAM_MAP.get(name, name)

def output_path(season):
    return FIXTURE_DIR / f"premier_league_{season}.csv"

def _season_code(season):
    # 2026-27 -> 2627
    return season[2:4] + season[-2:]

def known_teams(season):
    """
    Build the allowed-team set from our own season data.
    This prevents article notes containing 'X v Y' from becoming fixtures.
    """
    teams=set()

    # Best source: current raw football-data file.
    raw_candidates = [
        RAW_DIR / f"{season}.csv",
        RAW_DIR / f"{_season_code(season)}_E0.csv",
    ]
    for path in raw_candidates:
        if not path.exists():
            continue
        try:
            df=pd.read_csv(path,encoding="cp1252")
        except Exception:
            try:
                df=pd.read_csv(path,encoding="utf-8-sig")
            except Exception:
                continue
        if "HomeTeam" in df.columns and "AwayTeam" in df.columns:
            vals=pd.concat([df["HomeTeam"],df["AwayTeam"]]).dropna().astype(str)
            teams.update(canonical(x) for x in vals)

    # Fallback: generated team-match table for the season.
    table=TABLES/"team_match_stats.csv"
    if table.exists():
        try:
            df=pd.read_csv(table)
            if "season" in df and "team" in df:
                vals=df[df["season"].astype(str)==season]["team"].dropna().astype(str)
                teams.update(canonical(x) for x in vals)
        except Exception:
            pass

    return teams

def parse_official_page(html, season):
    allowed=known_teams(season)
    if len(allowed) < 20:
        raise ValueError(
            f"Could identify only {len(allowed)} valid teams for {season}; "
            "refusing to parse official schedule without a reliable whitelist."
        )

    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text("\n")
    lines=[re.sub(r"\s+"," ",x).strip() for x in text.splitlines()]
    lines=[x for x in lines if x]

    season_start=int(season[:4])
    current_year=season_start
    last_month=None
    current_date=None
    fixtures=[]

    for line in lines:
        dm=DAY_RE.match(line)
        if dm and dm.group(3) in MONTHS:
            day=int(dm.group(2))
            month=MONTHS[dm.group(3)]
            explicit_year=dm.group(4)
            if explicit_year:
                current_year=int(explicit_year)
            elif last_month is not None and month < last_month:
                current_year += 1
            last_month=month
            try:
                current_date=datetime(current_year,month,day).date()
            except ValueError:
                current_date=None
            continue

        if current_date is None:
            continue

        fm=FIX_RE.match(line)
        if not fm:
            continue

        time,home,away=fm.groups()
        home,away=canonical(home),canonical(away)

        # Critical guard: both sides must be actual teams in this PL season.
        if home not in allowed or away not in allowed:
            continue
        if home == away:
            continue

        fixtures.append({
            "match_date":current_date.isoformat(),
            "kickoff_time":time or "",
            "home_team":home,
            "away_team":away,
        })

    seen=set()
    clean=[]
    for fx in fixtures:
        key=(fx["match_date"],fx["home_team"],fx["away_team"])
        if key not in seen:
            seen.add(key)
            clean.append(fx)

    # Strong integrity check. Never poison the cache with a malformed scrape.
    if len(clean) != 380:
        raise ValueError(
            f"Official fixture parser found {len(clean)} valid matches, expected exactly 380. "
            "Existing cache will be kept."
        )

    # PL fixture article is published in match-round order, 10 fixtures each.
    for i,fx in enumerate(clean):
        fx["match_round"]=i//10+1
        fx["season"]=season
        fx["source"]="premierleague.com"
        fx["synced_at"]=datetime.now().isoformat(timespec="seconds")

    df=pd.DataFrame(clean)

    round_counts=df.groupby("match_round").size()
    if len(round_counts)!=38 or not (round_counts==10).all():
        raise ValueError(
            "Parsed schedule failed round integrity check: expected 38 rounds x 10 fixtures."
        )

    # Each ordered home-away pairing should occur once in the schedule.
    if df.duplicated(["home_team","away_team"]).any():
        raise ValueError("Parsed schedule contains duplicate home-away fixtures.")

    return df

def sync_fixtures(season="2026-27", force=False):
    path=output_path(season)

    if path.exists() and not force:
        age=datetime.now()-datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=12):
            cached=pd.read_csv(path)
            # Do not trust old malformed 381-row cache.
            if len(cached)==380:
                return cached

    url=OFFICIAL_URLS.get(season)
    if not url:
        if path.exists():
            return pd.read_csv(path)
        raise ValueError(f"No official fixture source configured for season {season}.")

    headers={
        "User-Agent":"Mozilla/5.0 PL-Analytika/2.0",
        "Accept-Language":"en-GB,en;q=0.9",
    }

    try:
        r=requests.get(url,headers=headers,timeout=30)
        r.raise_for_status()
        df=parse_official_page(r.text,season)
        # Only write after every validation has passed.
        df.to_csv(path,index=False,encoding="utf-8-sig")
        return df
    except Exception:
        # A previously valid cache is safer than a broken live scrape.
        if path.exists():
            cached=pd.read_csv(path)
            if len(cached)==380:
                return cached
        raise

def load_fixtures(season="2026-27", auto_sync=True):
    path=output_path(season)
    if auto_sync:
        try:
            return sync_fixtures(season)
        except Exception:
            if path.exists():
                cached=pd.read_csv(path)
                if len(cached)==380:
                    return cached
            raise
    if not path.exists():
        raise FileNotFoundError(path)
    df=pd.read_csv(path)
    if len(df)!=380:
        raise ValueError(f"Cached fixture file has {len(df)} rows; expected 380.")
    return df

def current_round(schedule, completed_matches=None, today=None):
    x=schedule.copy()
    x["match_date_dt"]=pd.to_datetime(x["match_date"],errors="coerce")

    completed=set()
    if completed_matches is not None and len(completed_matches):
        for _,r in completed_matches.iterrows():
            completed.add((str(r["home_team"]),str(r["away_team"])))

    x["played"]=[
        (str(r.home_team),str(r.away_team)) in completed
        for r in x.itertuples()
    ]

    incomplete=x.groupby("match_round")["played"].all()
    candidates=incomplete[~incomplete].index.tolist()
    rnd=int(min(candidates)) if candidates else int(x["match_round"].max())

    return rnd,x[x["match_round"]==rnd].copy()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--season",default="2026-27")
    p.add_argument("--force",action="store_true")
    args=p.parse_args()
    df=sync_fixtures(args.season,force=args.force)
    print(f"{args.season}: {len(df)} validated fixtures")
    print(f"Rounds: {df.match_round.nunique()} x 10")
    print(output_path(args.season))

if __name__=="__main__":
    main()
