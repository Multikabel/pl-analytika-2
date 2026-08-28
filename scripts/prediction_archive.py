from pathlib import Path
from datetime import datetime
import hashlib
import json
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent.parent
LOG_PATH = BASE / "data" / "predictions" / "prediction_log.csv"
TEAM_MATCH_PATH = BASE / "data" / "tables" / "team_match_stats.csv"

MARKET_TO_ACTUAL = {
    "fouls": "fouls_committed",
    "corners": "corners_for",
    "yellow_cards": "yellow_cards",
}

COLUMNS = [
    "prediction_id","created_at","season","match_round","match_date",
    "home_team","away_team","referee","team","venue","market","line",
    "prediction","p_over","fair_over","model_version","selection_source","status",
    "actual_value","result","settled_at"
]

def _empty_log():
    return pd.DataFrame(columns=COLUMNS)

def load_log():
    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        x = _empty_log()
        x.to_csv(LOG_PATH,index=False,encoding="utf-8-sig")
        return x
    x = pd.read_csv(LOG_PATH)
    for c in COLUMNS:
        if c not in x.columns:
            x[c] = np.nan
    return x[COLUMNS]

def _prediction_id(row):
    raw = "|".join([
        str(row.get("season","")),
        str(row.get("match_date","")),
        str(row.get("home_team","")),
        str(row.get("away_team","")),
        str(row.get("team","")),
        str(row.get("market","")),
        str(row.get("line","")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

def candidates_from_scored(scored, min_fair=2.0):
    """
    One archived tip per team + market:
    highest probability Over line whose model fair odds are >= min_fair.
    """
    if scored is None or len(scored)==0:
        return pd.DataFrame()
    x=scored[pd.to_numeric(scored["fair_over"],errors="coerce")>=float(min_fair)].copy()
    if x.empty:
        return x
    x=x.sort_values(["team","market","p_over"],ascending=[True,True,False])
    x=x.groupby(
        ["season","match_date","home_team","away_team","team","market"],
        as_index=False
    ).first()
    return x

def archive_selected_predictions(selected, match_round, model_version="v1.0", selection_source="manual"):
    """Save only tips explicitly selected by the user."""
    if selected is None or len(selected)==0:
        return 0
    log=load_log()
    now=datetime.now().isoformat(timespec="seconds")
    rows=[]
    for _,r in selected.iterrows():
        rec={
            "created_at":now,"season":r.get("season"),"match_round":match_round,
            "match_date":r.get("match_date"),"home_team":r.get("home_team"),
            "away_team":r.get("away_team"),"referee":r.get("referee",""),
            "team":r.get("team"),"venue":r.get("venue"),"market":r.get("market"),
            "line":float(r.get("line")),"prediction":float(r.get("prediction")),
            "p_over":float(r.get("p_over")),"fair_over":float(r.get("fair_over")),
            "model_version":model_version,"selection_source":selection_source,
            "status":"pending","actual_value":np.nan,"result":"","settled_at":"",
        }
        rec["prediction_id"]=_prediction_id(rec)
        rows.append(rec)
    add=pd.DataFrame(rows)
    for c in COLUMNS:
        if c not in add.columns: add[c]=np.nan
    add=add[COLUMNS]
    existing=set(log["prediction_id"].astype(str)) if len(log) else set()
    add=add[~add["prediction_id"].astype(str).isin(existing)]
    if add.empty: return 0
    pd.concat([log,add],ignore_index=True).to_csv(LOG_PATH,index=False,encoding="utf-8-sig")
    return len(add)

def archive_predictions(*args, **kwargs):
    # Legacy automatic recording is intentionally disabled.
    return 0

def settle_predictions():
    log=load_log()
    if log.empty:
        return {"settled":0,"wins":0,"losses":0}
    if not TEAM_MATCH_PATH.exists():
        return {"settled":0,"wins":0,"losses":0}

    tm=pd.read_csv(TEAM_MATCH_PATH)
    pending=log["status"].fillna("").eq("pending")
    settled=0; wins=0; losses=0
    now=datetime.now().isoformat(timespec="seconds")

    for idx,r in log[pending].iterrows():
        q=tm[
            (tm["season"].astype(str)==str(r["season"])) &
            (tm["match_date"].astype(str)==str(r["match_date"])) &
            (tm["team"].astype(str)==str(r["team"])) &
            (tm["opponent"].astype(str)==(
                str(r["away_team"]) if str(r["team"])==str(r["home_team"]) else str(r["home_team"])
            ))
        ]
        if q.empty:
            continue
        actual_col=MARKET_TO_ACTUAL.get(str(r["market"]))
        if not actual_col or actual_col not in q.columns:
            continue
        actual=pd.to_numeric(q.iloc[0][actual_col],errors="coerce")
        if pd.isna(actual):
            continue

        line=float(r["line"])
        # Current archive contains half-lines, so there is no push.
        result="WIN" if float(actual)>line else "LOSS"
        log.at[idx,"actual_value"]=float(actual)
        log.at[idx,"result"]=result
        log.at[idx,"status"]="settled"
        log.at[idx,"settled_at"]=now
        settled+=1
        wins += result=="WIN"
        losses += result=="LOSS"

    if settled:
        log.to_csv(LOG_PATH,index=False,encoding="utf-8-sig")
    return {"settled":settled,"wins":wins,"losses":losses}

def summary_stats(log=None):
    if log is None:
        log=load_log()
    s=log[log["status"].eq("settled")].copy()
    if s.empty:
        return {
            "tips":0,"wins":0,"losses":0,"hit_rate":np.nan,
            "avg_fair":np.nan
        }
    wins=int((s["result"]=="WIN").sum())
    losses=int((s["result"]=="LOSS").sum())
    return {
        "tips":len(s),
        "wins":wins,
        "losses":losses,
        "hit_rate":wins/len(s),
        "avg_fair":pd.to_numeric(s["fair_over"],errors="coerce").mean(),
    }

if __name__=="__main__":
    result=settle_predictions()
    print(json.dumps(result,indent=2))
