import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from update_fixtures import load_fixtures,current_round
from update_officials import sync_officials,canonical_referee
from score_round import score_fixtures
from model_prediction_stats import snapshot

BASE=Path(__file__).resolve().parent.parent
TABLES=BASE/"data"/"tables"
LOG_PATH=BASE/"data"/"predictions"/"model_prediction_log.csv"


def utc_now():
    return datetime.now(timezone.utc)


def valid_referee(value):
    if not isinstance(value, str) or not value.strip():
        return False
    parts=value.strip().lower().split()
    if any(p in {"unknown", "tbd", "tbc", "default", "fallback", "none", "null", "nan"} for p in parts):
        return False
    # Appointments are names, never a numeric ID or an unspecified placeholder.
    return len(parts)>=2 and all(any(c.isalpha() for c in p) and
                                all(c.isalpha() or c in ".'-’" for c in p) for p in parts)


def first_kickoff(round_df):
    # The validated feed stores UK-local wall time, including summer time.
    times=[]
    for r in round_df.itertuples():
        dt=datetime.strptime(f"{r.match_date} {r.kickoff_time}", "%Y-%m-%d %H:%M")
        instant=pd.Timestamp(dt).tz_localize("Europe/London", ambiguous="NaT",
                                            nonexistent="NaT")
        if pd.isna(instant):
            raise ValueError("ambiguous or nonexistent UK kickoff time")
        times.append(instant.tz_convert("UTC"))
    return min(times)

def main():
    tm=pd.read_csv(TABLES/"team_match_stats.csv")
    season=sorted(tm.season.dropna().astype(str).unique())[-1]
    completed=tm[(tm.season==season)&(tm.venue=="H")][["team","opponent"]].rename(
        columns={"team":"home_team","opponent":"away_team"}
    )
    schedule=load_fixtures(season,auto_sync=True)
    rnd,round_df=current_round(schedule,completed)

    def skip(reason):
        print(f"MW{rnd} snapshot skipped: {reason}")

    keys=[(r.home_team,r.away_team) for r in round_df.itertuples()]
    if (len(keys)!=10 or len(set(keys))!=10 or
            any(not isinstance(t,str) or not t.strip() for pair in keys for t in pair) or
            any(h==a for h,a in keys) or
            not round_df.season.astype(str).eq(season).all()):
        skip("invalid expected fixture identities (expected 10 matches)")
        return
    # Read directly: load_log() can enrich/rewrite historical archives.
    if LOG_PATH.exists():
        try:
            log=pd.read_csv(LOG_PATH)
            existing=log[log.season.astype(str).eq(season) &
                         pd.to_numeric(log.match_round,errors="coerce").eq(rnd)]
        except (OSError, ValueError, AttributeError, KeyError) as exc:
            skip(f"archive cannot be checked: {exc}")
            return
        if not existing.empty:
            skip("snapshot already has archived rows; preserving original snapshot")
            return
    try:
        kickoff=first_kickoff(round_df)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        skip(f"kickoff cannot be verified: {exc}")
        return
    if round_df.played.any() or utc_now()>=kickoff:
        skip("first kickoff reached or a match already played")
        return
    try:
        officials=sync_officials(rnd)
    except Exception as exc:
        skip(f"officials synchronization failed: {exc}")
        return
    required={"home_team","away_team","referee","match_round"}
    if officials is None or not required.issubset(officials.columns):
        skip("officials incomplete (0/10)")
        return
    officials=officials[pd.to_numeric(officials.match_round,errors="coerce").eq(rnd)]
    if "season" in officials:
        officials=officials[officials.season.astype(str).eq(season)]
    appointments={}
    for home,away in keys:
        q=officials[officials.home_team.eq(home) & officials.away_team.eq(away)]
        if len(q)==1 and valid_referee(q.iloc[0].referee):
            appointments[(home,away)]=canonical_referee(q.iloc[0].referee)
    if len(appointments)!=10 or len(officials)!=10:
        skip(f"officials incomplete ({len(appointments)}/10); require unique matching appointments")
        return
    if utc_now()>=kickoff:
        skip("first kickoff reached during officials synchronization")
        return
    fixtures=[]
    for _,r in round_df.iterrows():
        fixtures.append({
            "home_team":r.home_team,"away_team":r.away_team,
            "match_date":r.match_date,"season":season,
            "referee":appointments[(r.home_team,r.away_team)],
        })
    scored=score_fixtures(fixtures)
    if utc_now()>=kickoff:
        skip("first kickoff reached during scoring")
        return
    added=snapshot(scored,rnd)
    print(f"Match Round {rnd}: archived {added} model point predictions.")

if __name__=="__main__":
    main()
