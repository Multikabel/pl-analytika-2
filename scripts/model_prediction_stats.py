from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import numpy as np
import pandas as pd
from github_persistence import enabled as github_enabled, read_csv as github_read_csv, write_csv as github_write_csv, merge_append_only

BASE=Path(__file__).resolve().parent.parent
LOG_PATH=BASE/"data"/"predictions"/"model_prediction_log.csv"
REMOTE_LOG_PATH="data/predictions/model_prediction_log.csv"
TEAM_MATCH_PATH=BASE/"data"/"tables"/"team_match_stats.csv"

MARKET_TO_ACTUAL={
    "fouls":"fouls_committed",
    "corners":"corners_for",
    "yellow_cards":"yellow_cards",
    "fouls_total":"fouls_committed",
    "corners_total":"corners_for",
    "yellow_cards_total":"yellow_cards",
}
TOTAL_MARKETS={"fouls_total","corners_total","yellow_cards_total"}

COLUMNS=[
    "model_prediction_id","created_at","season","match_round","match_date",
    "home_team","away_team","referee","team","venue","market",
    "prediction","test_line","status","actual_value","result",
    "error","abs_error","bias_direction","model_version","settled_at"
]

def load_log():
    # In Streamlit Cloud, always prefer the latest persistent GitHub copy.
    if github_enabled():
        try:
            x,_=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
            if x is not None:
                return x
        except Exception:
            pass

    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
        x=pd.DataFrame(columns=COLUMNS)
        x.to_csv(LOG_PATH,index=False,encoding="utf-8-sig")
        return x

    x=pd.read_csv(LOG_PATH)
    for c in COLUMNS:
        if c not in x.columns:
            x[c]=np.nan
    return x[COLUMNS]

def _save_log(log, message):
    for c in COLUMNS:
        if c not in log.columns:
            log[c]=np.nan
    log=log[COLUMNS]
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    log.to_csv(LOG_PATH,index=False,encoding="utf-8-sig")

    if not github_enabled():
        return

    remote,sha=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
    merged=merge_append_only(remote,log,key="model_prediction_id")
    ok,detail=github_write_csv(REMOTE_LOG_PATH,merged,message,sha=sha)
    if not ok:
        # One retry handles a simultaneous Actions/app commit.
        remote,sha=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
        merged=merge_append_only(remote,log,key="model_prediction_id")
        ok,detail=github_write_csv(REMOTE_LOG_PATH,merged,message,sha=sha)
        if not ok:
            raise RuntimeError(f"GitHub prediction-stat persistence failed: {detail}")

def _id(r):
    raw="|".join([
        str(r.get("season","")),str(r.get("match_date","")),
        str(r.get("home_team","")),str(r.get("away_team","")),
        str(r.get("team","")),str(r.get("market","")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

def prediction_test_line(prediction):
    """
    Highest standard half-line strictly below the point prediction.
    21.8 -> O21.5, 21.2 -> O20.5, 21.0 -> O20.5.
    """
    p=float(prediction)
    return max(0.5, math.ceil(p)-0.5)

def snapshot(scored, match_round, model_version="count-models-v1.4"):
    if scored is None or scored.empty:
        return 0
    # score_fixture contains many betting lines; point prediction is identical
    # within each team/market, so archive it exactly once.
    x=scored.sort_values("line").groupby(
        ["season","match_date","home_team","away_team","team","market"],
        as_index=False
    ).first()

    log=load_log()
    existing=set(log["model_prediction_id"].astype(str)) if len(log) else set()
    now=datetime.now().isoformat(timespec="seconds")
    rows=[]
    for _,r in x.iterrows():
        rec={
            "created_at":now,"season":r["season"],"match_round":match_round,
            "match_date":r["match_date"],"home_team":r["home_team"],
            "away_team":r["away_team"],"referee":r.get("referee",""),
            "team":r["team"],"venue":r.get("venue",""),
            "market":r["market"],"prediction":float(r["prediction"]),
            "test_line":prediction_test_line(r["prediction"]),
            "status":"pending","actual_value":np.nan,"result":"",
            "error":np.nan,"abs_error":np.nan,"bias_direction":"",
            "model_version":model_version,"settled_at":"",
        }
        rec["model_prediction_id"]=_id(rec)
        if rec["model_prediction_id"] not in existing:
            rows.append(rec)

    if not rows:
        return 0
    out=pd.concat([log,pd.DataFrame(rows)],ignore_index=True)
    out=out[COLUMNS]
    _save_log(out,"stats: archive model predictions")
    return len(rows)

def settle():
    log=load_log()
    if log.empty or not TEAM_MATCH_PATH.exists():
        return {"settled":0}
    tm=pd.read_csv(TEAM_MATCH_PATH)
    pending=log.status.fillna("").eq("pending")
    now=datetime.now().isoformat(timespec="seconds")
    count=0

    for idx,r in log[pending].iterrows():
        market=str(r.market)
        actual_col=MARKET_TO_ACTUAL.get(market)
        if not actual_col or actual_col not in tm.columns:
            continue

        if market in TOTAL_MARKETS:
            q=tm[
                (tm.season.astype(str)==str(r.season)) &
                (tm.match_date.astype(str)==str(r.match_date)) &
                (tm.team.astype(str).isin([str(r.home_team),str(r.away_team)]))
            ]
            if len(q)<2:
                continue
            vals=pd.to_numeric(q[actual_col],errors="coerce")
            if vals.isna().any():
                continue
            actual=float(vals.sum())
        else:
            q=tm[
                (tm.season.astype(str)==str(r.season)) &
                (tm.match_date.astype(str)==str(r.match_date)) &
                (tm.team.astype(str)==str(r.team))
            ]
            if q.empty:
                continue
            actual=pd.to_numeric(q.iloc[0][actual_col],errors="coerce")
            if pd.isna(actual):
                continue
            actual=float(actual)

        pred=float(r.prediction)
        line=float(r.test_line)
        err=actual-pred
        result="HIT" if actual>line else "MISS"
        direction="Podstřeleno" if err>0 else ("Přestřeleno" if err<0 else "Přesně")

        log.at[idx,"actual_value"]=actual
        log.at[idx,"result"]=result
        log.at[idx,"error"]=err
        log.at[idx,"abs_error"]=abs(err)
        log.at[idx,"bias_direction"]=direction
        log.at[idx,"status"]="settled"
        log.at[idx,"settled_at"]=now
        count+=1

    if count:
        _save_log(log,"stats: settle model predictions")
    return {"settled":count}

def summary(log=None):
    if log is None:
        log=load_log()
    s=log[log.status.eq("settled")].copy()
    if s.empty:
        return {"n":0,"hit_rate":np.nan,"mae":np.nan,"bias":np.nan,
                "under_rate":np.nan,"over_rate":np.nan}
    err=pd.to_numeric(s.error,errors="coerce")
    return {
        "n":len(s),
        "hit_rate":(s.result=="HIT").mean(),
        "mae":pd.to_numeric(s.abs_error,errors="coerce").mean(),
        "bias":err.mean(),
        "under_rate":(err>0).mean(),
        "over_rate":(err<0).mean(),
    }

if __name__=="__main__":
    print(json.dumps(settle(),indent=2,ensure_ascii=False))
