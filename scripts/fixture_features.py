from pathlib import Path
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
TEAM_MATCH_PATH=BASE/"data"/"tables"/"team_match_stats.csv"
REF_MATCH_PATH=BASE/"data"/"tables"/"referee_match_stats.csv"

def _mean(df,col,n=None):
    if df.empty or col not in df: return np.nan
    x=df if n is None else df.tail(n)
    s=pd.to_numeric(x[col],errors="coerce").dropna()
    return float(s.mean()) if len(s) else np.nan

def _team_features(tm,team,opponent,venue,season,date):
    date=pd.Timestamp(date)
    all_hist=tm[(tm.team==team)&(tm.match_date_dt<date)].sort_values(["match_date_dt","match_id"])
    sh=all_hist[all_hist.season==season]
    vh=sh[sh.venue==venue]
    out={"days_rest":np.nan}
    if len(all_hist):
        out["days_rest"]=(date-all_hist.match_date_dt.max()).days

    metrics=["fouls_committed","fouls_suffered","corners_for","corners_against",
             "yellow_cards","yellow_cards_opponent","shots_for","shots_against",
             "shots_on_target_for","shots_on_target_against","goals_for","goals_against"]
    for c in metrics:
        out[f"season_{c}_avg"]=_mean(sh,c)
        out[f"venue_{c}_avg"]=_mean(vh,c)
        for n in (3,5,10):
            out[f"last{n}_{c}_avg"]=_mean(sh,c,n)
    for c in ["fouls_committed","fouls_suffered","corners_for","corners_against","yellow_cards","points"]:
        out[f"pl_last5_{c}_avg"]=_mean(all_hist,c,5)

    h2h=all_hist[all_hist.opponent==opponent]
    for c in ["fouls_committed","fouls_suffered","corners_for","corners_against",
              "yellow_cards","yellow_cards_opponent"]:
        out[f"h2h_{c}_avg_before"]=_mean(h2h,c)
        out[f"h2h_last3_{c}_avg_before"]=_mean(h2h,c,3)
    out["h2h_matches_before"]=len(h2h)
    return out

def _league_features(tm,season,date):
    date=pd.Timestamp(date)
    hist=tm[(tm.match_date_dt<date)&(tm.venue=="H")].copy()
    sh=hist[hist.season==season]
    out={}
    def match_metric(df,home_col,away_col):
        if df.empty:return np.nan
        # Locate away rows by match_id
        ids=df.match_id.tolist()
        away=tm[(tm.match_id.isin(ids))&(tm.venue=="A")].set_index("match_id")
        h=df.set_index("match_id")
        vals=pd.to_numeric(h[home_col],errors="coerce")+pd.to_numeric(away[away_col],errors="coerce")
        return float(vals.mean()) if vals.notna().any() else np.nan

    out["league_total_fouls_avg_before"]=match_metric(sh,"fouls_committed","fouls_committed")
    out["league_total_corners_avg_before"]=match_metric(sh,"corners_for","corners_for")
    out["league_total_yellow_avg_before"]=match_metric(sh,"yellow_cards","yellow_cards")
    out["home_fouls_avg_before"]=_mean(sh,"fouls_committed")
    away_sh=tm[(tm.season==season)&(tm.match_date_dt<date)&(tm.venue=="A")]
    out["away_fouls_avg_before"]=_mean(away_sh,"fouls_committed")

    recent=hist.tail(20)
    out["pl_last20_league_total_fouls_avg_before"]=match_metric(recent,"fouls_committed","fouls_committed")
    out["pl_last20_league_total_corners_avg_before"]=match_metric(recent,"corners_for","corners_for")
    out["pl_last20_league_total_yellow_avg_before"]=match_metric(recent,"yellow_cards","yellow_cards")
    return out

def _ref_features(rm,referee,season,date):
    date=pd.Timestamp(date)
    if not referee:
        return {}
    allh=rm[(rm.referee==referee)&(rm.match_date_dt<date)].sort_values(["match_date_dt","match_id"])
    sh=allh[allh.season==season]
    out={}
    fields=["home_fouls","away_fouls","total_fouls","home_yellow","away_yellow","total_yellow","total_red"]
    for c in fields:
        out[f"referee_{c}_avg_before"]=_mean(sh,c)
        if c in ("total_fouls","total_yellow"):
            out[f"referee_last5_{c}_avg_before"]=_mean(sh,c,5)
            out[f"referee_last10_{c}_avg_before"]=_mean(sh,c,10)
        out[f"referee_pl_{c}_avg_before"]=_mean(allh,c)
        if c in ("total_fouls","total_yellow"):
            out[f"referee_pl_last10_{c}_avg_before"]=_mean(allh,c,10)
    out["referee_matches_before"]=len(sh)
    out["referee_pl_matches_before"]=len(allh)
    return out

def build_fixture_rows(home,away,referee,date,season):
    if not TEAM_MATCH_PATH.exists():
        raise FileNotFoundError(f"Missing {TEAM_MATCH_PATH}. Run update_data.py first.")
    tm=pd.read_csv(TEAM_MATCH_PATH)
    tm["match_date_dt"]=pd.to_datetime(tm["match_date"])
    if REF_MATCH_PATH.exists():
        rm=pd.read_csv(REF_MATCH_PATH)
        rm["match_date_dt"]=pd.to_datetime(rm["match_date"])
    else:
        rm=pd.DataFrame(columns=["referee","season","match_date_dt"])

    known=set(tm.team.unique())
    missing=[x for x in (home,away) if x not in known]
    if missing:
        raise ValueError(f"Unknown team(s): {missing}. Available example: {sorted(known)[:10]}")

    league=_league_features(tm,season,date)
    ref=_ref_features(rm,referee,season,date)

    rows=[]
    for team,opp,venue in [(home,away,"H"),(away,home,"A")]:
        own=_team_features(tm,team,opp,venue,season,date)
        other=_team_features(tm,opp,team,"A" if venue=="H" else "H",season,date)
        row={
            "match_id":f"UPCOMING::{season}::{date}::{home}::{away}",
            "season":season,"match_date":date,"team":team,"opponent":opp,
            "venue":venue,"referee":referee
        }
        row.update(own); row.update(league); row.update(ref)
        row.update({f"opp_{k}":v for k,v in other.items()})
        # Opponent copies of league/ref fields exist in historical table; same match context applies.
        row.update({f"opp_{k}":v for k,v in league.items()})
        row.update({f"opp_{k}":v for k,v in ref.items()})
        rows.append(row)
    return pd.DataFrame(rows)
