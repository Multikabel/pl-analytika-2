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
    name=re.sub(r"^\*+|\*+$","",str(name)).strip()
    return TEAM_MAP.get(name,name)

def output_path(season):
    return FIXTURE_DIR / f"premier_league_{season}.csv"

def _season_code(season):
    return season[2:4]+season[-2:]

def known_teams(season):
    teams=set()
    raw_candidates=[
        RAW_DIR/f"{season}.csv",
        RAW_DIR/f"{_season_code(season)}_E0.csv",
    ]
    for path in raw_candidates:
        if not path.exists():
            continue
        df=None
        for enc in ("cp1252","utf-8-sig","latin1"):
            try:
                df=pd.read_csv(path,encoding=enc)
                break
            except Exception:
                pass
        if df is not None and "HomeTeam" in df and "AwayTeam" in df:
            vals=pd.concat([df.HomeTeam,df.AwayTeam]).dropna().astype(str)
            teams.update(canonical(x) for x in vals)

    table=TABLES/"team_match_stats.csv"
    if table.exists():
        try:
            df=pd.read_csv(table)
            vals=df[df["season"].astype(str)==season]["team"].dropna().astype(str)
            teams.update(canonical(x) for x in vals)
        except Exception:
            pass
    return teams

def _validate_fixture_df(df,season,require_rounds=True):
    allowed=known_teams(season)
    if len(allowed)<20:
        return False
    if df is None or len(df)==0:
        return False

    x=df.copy()
    x["home_team"]=x["home_team"].map(canonical)
    x["away_team"]=x["away_team"].map(canonical)
    x=x[x.home_team.isin(allowed)&x.away_team.isin(allowed)]
    x=x[x.home_team!=x.away_team]
    x=x.drop_duplicates(["home_team","away_team"])

    if len(x)!=380:
        return False

    if require_rounds:
        if "match_round" not in x.columns:
            return False
        counts=x.groupby("match_round").size()
        if len(counts)!=38 or not (counts==10).all():
            return False
    return True

def repair_cached_schedule(df,season):
    """
    Salvage an old cache, including the previous 381-row cache:
    filter to valid season teams + one home/away pairing each.
    """
    if df is None or len(df)==0:
        return pd.DataFrame()

    allowed=known_teams(season)
    x=df.copy()
    for c in ("home_team","away_team"):
        if c not in x.columns:
            return pd.DataFrame()
        x[c]=x[c].map(canonical)

    x=x[
        x.home_team.isin(allowed) &
        x.away_team.isin(allowed) &
        (x.home_team!=x.away_team)
    ].copy()
    x=x.drop_duplicates(["home_team","away_team"],keep="first")

    if len(x)!=380:
        return pd.DataFrame()

    # Rebuild rounds deterministically from cached season order.
    # Existing valid match_round values are retained only if they are exactly 38x10.
    if "match_round" not in x.columns or not (
        x.groupby("match_round").size().shape[0]==38 and
        (x.groupby("match_round").size()==10).all()
    ):
        x=x.reset_index(drop=True)
        x["match_round"]=x.index//10+1

    x["season"]=season
    return x.reset_index(drop=True)

def parse_live_page(html,season):
    allowed=known_teams(season)
    if len(allowed)<20:
        raise ValueError(f"Only {len(allowed)} valid teams identified for {season}.")

    soup=BeautifulSoup(html,"html.parser")
    lines=[re.sub(r"\s+"," ",x).strip() for x in soup.get_text("\n").splitlines()]
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
            if dm.group(4):
                current_year=int(dm.group(4))
            elif last_month is not None and month<last_month:
                current_year+=1
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
        if home not in allowed or away not in allowed or home==away:
            continue

        fixtures.append({
            "match_date":current_date.isoformat(),
            "kickoff_time":time or "",
            "home_team":home,
            "away_team":away,
        })

    x=pd.DataFrame(fixtures)
    if len(x):
        x=x.drop_duplicates(["home_team","away_team"],keep="first").reset_index(drop=True)
    return x

def merge_live_with_cache(live,cache,season):
    """
    Live page controls dates/times for fixtures it exposes.
    Missing fixtures are restored from the repaired season cache.
    """
    repaired=repair_cached_schedule(cache,season)
    if repaired.empty:
        if len(live)==380:
            out=live.copy().reset_index(drop=True)
            out["match_round"]=out.index//10+1
            out["season"]=season
            return out
        raise ValueError(
            f"Live page exposed {len(live)} fixtures and no repairable 380-match cache is available."
        )

    # Keep season/order/round structure from repaired cache.
    out=repaired.copy()

    if len(live):
        live_idx=live.set_index(["home_team","away_team"])
        for idx,row in out.iterrows():
            key=(row.home_team,row.away_team)
            if key in live_idx.index:
                lr=live_idx.loc[key]
                # Handle theoretical duplicate index safely.
                if isinstance(lr,pd.DataFrame):
                    lr=lr.iloc[0]
                out.at[idx,"match_date"]=lr["match_date"]
                out.at[idx,"kickoff_time"]=lr.get("kickoff_time","")

    out["source"]="premierleague.com merged"
    out["synced_at"]=datetime.now().isoformat(timespec="seconds")
    out["season"]=season

    if not _validate_fixture_df(out,season,require_rounds=True):
        raise ValueError("Merged fixture schedule failed 380 / 38x10 integrity validation.")

    return out.reset_index(drop=True)

def sync_fixtures(season="2026-27",force=False):
    path=output_path(season)

    old_cache=pd.DataFrame()
    if path.exists():
        try:
            old_cache=pd.read_csv(path)
        except Exception:
            pass

    # Repair malformed prior cache before doing anything else.
    repaired=repair_cached_schedule(old_cache,season)
    if len(repaired)==380 and (old_cache is None or len(old_cache)!=380):
        repaired["source"]="repaired local cache"
        repaired["synced_at"]=datetime.now().isoformat(timespec="seconds")
        repaired.to_csv(path,index=False,encoding="utf-8-sig")
        old_cache=repaired.copy()

    if path.exists() and not force:
        age=datetime.now()-datetime.fromtimestamp(path.stat().st_mtime)
        if age<timedelta(hours=12):
            cached=pd.read_csv(path)
            if _validate_fixture_df(cached,season):
                return cached

    url=OFFICIAL_URLS.get(season)
    if not url:
        if _validate_fixture_df(repaired,season):
            return repaired
        raise ValueError(f"No official source configured for {season}.")

    headers={
        "User-Agent":"Mozilla/5.0 PL-Analytika/2.0",
        "Accept-Language":"en-GB,en;q=0.9",
    }

    r=requests.get(url,headers=headers,timeout=30)
    r.raise_for_status()
    live=parse_live_page(r.text,season)

    print(f"Official page exposed {len(live)} valid fixtures in text.")

    merged=merge_live_with_cache(live,old_cache,season)
    merged.to_csv(path,index=False,encoding="utf-8-sig")
    return merged

def load_fixtures(season="2026-27",auto_sync=True):
    path=output_path(season)
    if auto_sync:
        try:
            return sync_fixtures(season)
        except Exception:
            if path.exists():
                cached=repair_cached_schedule(pd.read_csv(path),season)
                if len(cached)==380:
                    return cached
            raise

    if not path.exists():
        raise FileNotFoundError(path)
    cached=repair_cached_schedule(pd.read_csv(path),season)
    if len(cached)!=380:
        raise ValueError("Cached fixture schedule cannot be repaired to 380 fixtures.")
    return cached

def current_round(schedule,completed_matches=None,today=None):
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
    rnd=int(min(candidates)) if candidates else int(x.match_round.max())
    return rnd,x[x.match_round==rnd].copy()

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
