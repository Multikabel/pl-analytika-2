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
    "fouls_total": "fouls_committed",
    "corners_total": "corners_for",
    "yellow_cards_total": "yellow_cards",
}
TOTAL_MARKETS={"fouls_total","corners_total","yellow_cards_total"}

COLUMNS = [
    "prediction_id","created_at","season","match_round","match_date",
    "home_team","away_team","referee","team","venue","market","line",
    "prediction","p_over","fair_over","bookmaker_odds","stake_units",
    "model_version","selection_source","status","actual_value","result",
    "profit_units","settled_at"
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
            "bookmaker_odds":float(r.get("bookmaker_odds")),"stake_units":float(r.get("stake_units",1.0)),
            "model_version":model_version,"selection_source":selection_source,
            "status":"pending","actual_value":np.nan,"result":"","profit_units":np.nan,"settled_at":"",
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
        market=str(r["market"])
        actual_col=MARKET_TO_ACTUAL.get(market)
        if not actual_col or actual_col not in tm.columns:
            continue

        if market in TOTAL_MARKETS:
            q=tm[
                (tm["season"].astype(str)==str(r["season"])) &
                (tm["match_date"].astype(str)==str(r["match_date"])) &
                (tm["team"].astype(str).isin([str(r["home_team"]),str(r["away_team"])]))
            ]
            if len(q)<2:
                continue
            vals=pd.to_numeric(q[actual_col],errors="coerce")
            if vals.isna().any():
                continue
            actual=float(vals.sum())
        else:
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
            actual=pd.to_numeric(q.iloc[0][actual_col],errors="coerce")
            if pd.isna(actual):
                continue

        line=float(r["line"])
        # Current archive contains half-lines, so there is no push.
        result="WIN" if float(actual)>line else "LOSS"
        odds=pd.to_numeric(pd.Series([r.get("bookmaker_odds")]),errors="coerce").iloc[0]
        stake=pd.to_numeric(pd.Series([r.get("stake_units",1.0)]),errors="coerce").iloc[0]
        if pd.isna(stake) or stake<=0:
            stake=1.0
        if result=="WIN" and pd.notna(odds) and odds>1:
            profit=float(stake)*(float(odds)-1.0)
        elif result=="LOSS":
            profit=-float(stake)
        else:
            profit=np.nan

        log.at[idx,"actual_value"]=float(actual)
        log.at[idx,"result"]=result
        log.at[idx,"profit_units"]=profit
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
            "avg_fair":np.nan,"avg_bookmaker_odds":np.nan,
            "profit_units":0.0,"roi":np.nan,"staked_units":0.0
        }

    wins=int((s["result"]=="WIN").sum())
    losses=int((s["result"]=="LOSS").sum())
    odds=pd.to_numeric(s["bookmaker_odds"],errors="coerce")
    profit=pd.to_numeric(s["profit_units"],errors="coerce").fillna(0)
    stake=pd.to_numeric(s["stake_units"],errors="coerce").fillna(1.0)
    total_stake=float(stake.sum())
    total_profit=float(profit.sum())

    return {
        "tips":len(s),
        "wins":wins,
        "losses":losses,
        "hit_rate":wins/len(s),
        "avg_fair":pd.to_numeric(s["fair_over"],errors="coerce").mean(),
        "avg_bookmaker_odds":odds.mean(),
        "profit_units":total_profit,
        "staked_units":total_stake,
        "roi":(total_profit/total_stake) if total_stake>0 else np.nan,
    }

if __name__=="__main__":
    result=settle_predictions()
    print(json.dumps(result,indent=2))
