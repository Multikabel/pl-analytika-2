from pathlib import Path
import argparse
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BASE / "data" / "fixtures"
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
    "Tottenham Hotspur": "Tottenham",
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
    name = re.sub(r"\*+$","",str(name)).strip()
    return TEAM_MAP.get(name,name)

def output_path(season):
    return FIXTURE_DIR / f"premier_league_{season}.csv"

def parse_official_page(html, season):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+"," ",x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]

    season_start = int(season[:4])
    current_year = season_start
    last_month = None
    current_date = None
    fixtures = []

    for line in lines:
        dm = DAY_RE.match(line)
        if dm and dm.group(3) in MONTHS:
            day = int(dm.group(2))
            month = MONTHS[dm.group(3)]
            explicit_year = dm.group(4)
            if explicit_year:
                current_year = int(explicit_year)
            elif last_month is not None and month < last_month:
                current_year += 1
            last_month = month
            try:
                current_date = datetime(current_year, month, day).date()
            except ValueError:
                current_date = None
            continue

        if current_date is None:
            continue
        fm = FIX_RE.match(line)
        if not fm:
            continue

        time, home, away = fm.groups()
        home, away = canonical(home), canonical(away)

        # Exclude article/navigation text that happens to contain " v ".
        if len(home) > 40 or len(away) > 40:
            continue
        fixtures.append({
            "match_date": current_date.isoformat(),
            "kickoff_time": time or "",
            "home_team": home,
            "away_team": away,
        })

    # The official season article should yield all 380 fixtures.
    # Deduplicate while preserving order.
    seen=set(); clean=[]
    for fx in fixtures:
        key=(fx["match_date"],fx["home_team"],fx["away_team"])
        if key not in seen:
            seen.add(key); clean.append(fx)

    if len(clean) < 300:
        raise ValueError(
            f"Official fixture parser found only {len(clean)} matches; "
            "page structure may have changed."
        )

    for i, fx in enumerate(clean):
        fx["match_round"] = i // 10 + 1
        fx["season"] = season
        fx["source"] = "premierleague.com"
        fx["synced_at"] = datetime.now().isoformat(timespec="seconds")

    return pd.DataFrame(clean)

def sync_fixtures(season="2026-27", force=False):
    path = output_path(season)
    if path.exists() and not force:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=12):
            return pd.read_csv(path)

    url = OFFICIAL_URLS.get(season)
    if not url:
        if path.exists():
            return pd.read_csv(path)
        raise ValueError(f"No official fixture source configured for season {season}.")

    headers = {
        "User-Agent": "Mozilla/5.0 PL-Analytika/2.0",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    df = parse_official_page(r.text, season)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df

def load_fixtures(season="2026-27", auto_sync=True):
    path=output_path(season)
    if auto_sync:
        try:
            return sync_fixtures(season)
        except Exception:
            if path.exists():
                return pd.read_csv(path)
            raise
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)

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

    # First match round that still contains an unplayed fixture.
    incomplete=x.groupby("match_round")["played"].all()
    candidates=incomplete[~incomplete].index.tolist()
    if candidates:
        rnd=int(min(candidates))
    else:
        rnd=int(x["match_round"].max())

    return rnd, x[x["match_round"]==rnd].copy()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--season",default="2026-27")
    p.add_argument("--force",action="store_true")
    args=p.parse_args()
    df=sync_fixtures(args.season,force=args.force)
    print(f"{args.season}: {len(df)} fixtures")
    print(output_path(args.season))

if __name__=="__main__":
    main()
