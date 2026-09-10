from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import numpy as np
import pandas as pd
from github_persistence import enabled as github_enabled, read_csv as github_read_csv, write_csv as github_write_csv, merge_append_only
from count_common import load_config
from scipy.stats import poisson, nbinom

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

RANGE_WIDTHS={
    "fouls":3,
    "corners":2,
    "yellow_cards":2,
    "fouls_total":4,
    "corners_total":3,
    "yellow_cards_total":2,
}

def _pmf_values(mu,cfg,total_components=None):
    """Return integer support and PMF using the same count family as scoring."""
    mu=max(float(mu),0.05)
    dist=cfg.get("distribution",{"type":"poisson"})
    if dist.get("type")=="negative_binomial":
        alpha=float(dist.get("alpha",0.0))
        if total_components is not None:
            mh,ma=[max(float(v),0.05) for v in total_components]
            var=mh + alpha*mh**2 + ma + alpha*ma**2
            if var>mu:
                alpha=(var-mu)/(mu**2)
        if alpha>0:
            n=1.0/alpha
            prob=n/(n+mu)
            hi=int(max(25, nbinom.ppf(0.999999,n,prob)))
            xs=np.arange(0,hi+1,dtype=int)
            return xs,nbinom.pmf(xs,n,prob)
    hi=int(max(25, poisson.ppf(0.999999,mu)))
    xs=np.arange(0,hi+1,dtype=int)
    return xs,poisson.pmf(xs,mu)

def _best_contiguous_range(mu,market,total_components=None):
    """Highest-probability contiguous integer window with market-specific width."""
    base=market.replace("_total","")
    cfg=load_config(base)
    width=int(RANGE_WIDTHS[market])
    xs,pmf=_pmf_values(mu,cfg,total_components=total_components)
    if len(xs)<=width:
        return int(xs[0]),int(xs[-1]),float(pmf.sum())
    sums=np.convolve(pmf,np.ones(width),mode="valid")
    start=int(np.argmax(sums))
    return int(xs[start]),int(xs[start+width-1]),float(sums[start])

def enrich_prediction_ranges(log):
    """Fill range fields from archived point predictions without changing the predictions."""
    if log is None or log.empty:
        return log,0
    out=log.copy(); changed=0
    for c in ["range_low","range_high","range_probability","range_result"]:
        if c not in out.columns: out[c]=np.nan if c!="range_result" else ""
    for idx,r in out.iterrows():
        if pd.notna(r.get("range_low")) and pd.notna(r.get("range_high")) and pd.notna(r.get("range_probability")):
            continue
        market=str(r.get("market",""))
        if market not in RANGE_WIDTHS: continue
        try: mu=float(r.get("prediction"))
        except Exception: continue
        comps=None
        if market.endswith("_total"):
            base=market.replace("_total","")
            sib=out[(out.season.astype(str)==str(r.get("season"))) &
                    (out.home_team.astype(str)==str(r.get("home_team"))) &
                    (out.away_team.astype(str)==str(r.get("away_team"))) &
                    (out.market.astype(str)==base) &
                    (out.team.astype(str)!="CELKEM")]
            vals=pd.to_numeric(sib.prediction,errors="coerce").dropna().tolist()
            if len(vals)>=2: comps=(float(vals[0]),float(vals[1]))
        lo,hi,prob=_best_contiguous_range(mu,market,total_components=comps)
        out.at[idx,"range_low"]=lo; out.at[idx,"range_high"]=hi
        out.at[idx,"range_probability"]=prob; changed+=1
    return out,changed


COLUMNS=[
    "model_prediction_id","created_at","season","match_round","match_date",
    "home_team","away_team","referee","team","venue","market",
    "prediction","test_line","range_low","range_high","range_probability","range_result",
    "status","actual_value","result","error","abs_error","bias_direction","model_version","settled_at"
]

def load_log():
    # In Streamlit Cloud, always prefer the latest persistent GitHub copy.
    if github_enabled():
        try:
            x,_=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
            if x is not None:
                return _dedupe_log(x)
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
    return _dedupe_log(x[COLUMNS])

def _save_log(log, message):
    for c in COLUMNS:
        if c not in log.columns:
            log[c]=np.nan
    log=_dedupe_log(log[COLUMNS])
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    log.to_csv(LOG_PATH,index=False,encoding="utf-8-sig")

    if not github_enabled():
        return

    remote,sha=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
    remote_raw=remote.copy() if remote is not None else pd.DataFrame(columns=COLUMNS)
    merged=_dedupe_log(pd.concat([remote_raw,log],ignore_index=True))
    # Avoid a GitHub commit when normalization/settlement changed nothing.
    try:
        before=remote_raw[COLUMNS].to_csv(index=False)
        after=merged[COLUMNS].to_csv(index=False)
        if before==after:
            return
    except Exception:
        pass
    ok,detail=github_write_csv(REMOTE_LOG_PATH,merged,message,sha=sha)
    if not ok:
        # One retry handles a simultaneous Actions/app commit.
        remote,sha=github_read_csv(REMOTE_LOG_PATH,COLUMNS)
        remote=pd.DataFrame(columns=COLUMNS) if remote is None else remote
        merged=_dedupe_log(pd.concat([remote,log],ignore_index=True))
        ok,detail=github_write_csv(REMOTE_LOG_PATH,merged,message,sha=sha)
        if not ok:
            raise RuntimeError(f"GitHub prediction-stat persistence failed: {detail}")

def _semantic_key(r):
    return "|".join([
        str(r.get("season","")),
        str(r.get("home_team","")),str(r.get("away_team","")),
        str(r.get("team","")),str(r.get("market","")),
    ])

def _id(r):
    # Match date is intentionally NOT part of the identity. Fixture dates can move
    # and a manual date mismatch must never create a second audit record.
    return hashlib.sha1(_semantic_key(r).encode("utf-8")).hexdigest()[:20]

def _dedupe_log(x):
    if x is None or x.empty:
        return x
    x=x.copy()
    for c in COLUMNS:
        if c not in x.columns: x[c]=np.nan
    x["_key"]=x.apply(_semantic_key,axis=1)
    x["_created"]=pd.to_datetime(x["created_at"],errors="coerce")
    rows=[]
    for _,g in x.sort_values("_created",na_position="last").groupby("_key",sort=False):
        # The earliest row is the immutable pre-match point prediction.
        keep=g.iloc[0].copy()

        # Migration/enrichment fields are allowed to be filled later.  When the
        # same semantic prediction exists in both an old GitHub copy and a newly
        # enriched local copy, take the newest non-empty range values instead of
        # throwing them away during deduplication.
        for c in ["range_low","range_high","range_probability","range_result"]:
            vals=g[c]
            if c=="range_result":
                valid=vals[vals.fillna("").astype(str).str.strip().ne("")]
            else:
                valid=vals[pd.notna(vals)]
            if len(valid):
                keep[c]=valid.iloc[-1]

        settled=g[g["status"].astype(str).eq("settled")]
        if len(settled):
            s=settled.sort_values("_created",na_position="last").iloc[-1]
            for c in ["status","actual_value","result","range_result","range_low","range_high","range_probability","error","abs_error","bias_direction","settled_at","match_date","match_round"]:
                keep[c]=s[c]
        keep["model_prediction_id"]=_id(keep)
        rows.append(keep)
    out=pd.DataFrame(rows).drop(columns=["_key","_created"],errors="ignore")
    return out[COLUMNS].reset_index(drop=True)

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
        ["season","home_team","away_team","team","market"],
        as_index=False
    ).first()

    log=load_log()
    log,_=enrich_prediction_ranges(log)
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
            "range_low":np.nan,"range_high":np.nan,"range_probability":np.nan,"range_result":"",
            "status":"pending","actual_value":np.nan,"result":"",
            "error":np.nan,"abs_error":np.nan,"bias_direction":"",
            "model_version":model_version,"settled_at":"",
        }
        rec["model_prediction_id"]=_id(rec)
        if rec["model_prediction_id"] not in existing:
            rows.append(rec)

    if not rows:
        # Also acts as a one-time migration: old date-based duplicate IDs are
        # collapsed in the persistent GitHub log even when this fixture was already saved.
        _save_log(log,"stats: normalize prediction identities")
        return 0
    out=pd.concat([log,pd.DataFrame(rows)],ignore_index=True)
    out,_=enrich_prediction_ranges(out)
    out=out[COLUMNS]
    _save_log(out,"stats: archive model predictions")
    return len(rows)

def settle():
    log=load_log()
    log,enriched=enrich_prediction_ranges(log)
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

        # Settle by season + fixture identity, not predicted date. Dates can move.
        home_q=tm[(tm.season.astype(str)==str(r.season)) &
                  (tm.team.astype(str)==str(r.home_team)) &
                  (tm.opponent.astype(str)==str(r.away_team)) &
                  (tm.venue.astype(str)=="H")]
        if home_q.empty:
            continue
        actual_match_date=str(home_q.iloc[-1].match_date)

        if market in TOTAL_MARKETS:
            mid=str(home_q.iloc[-1].match_id)
            q=tm[tm.match_id.astype(str)==mid]
            if len(q)<2: continue
            vals=pd.to_numeric(q[actual_col],errors="coerce")
            if vals.isna().any(): continue
            actual=float(vals.sum())
        else:
            opponent=str(r.away_team) if str(r.team)==str(r.home_team) else str(r.home_team)
            q=tm[(tm.season.astype(str)==str(r.season)) &
                 (tm.team.astype(str)==str(r.team)) &
                 (tm.opponent.astype(str)==opponent)]
            if q.empty: continue
            actual=pd.to_numeric(q.iloc[-1][actual_col],errors="coerce")
            if pd.isna(actual): continue
            actual=float(actual)

        log.at[idx,"match_date"]=actual_match_date

        pred=float(r.prediction)
        line=float(r.test_line)
        err=actual-pred
        result="HIT" if actual>line else "MISS"
        lo=pd.to_numeric(pd.Series([r.get("range_low")]),errors="coerce").iloc[0]
        hi=pd.to_numeric(pd.Series([r.get("range_high")]),errors="coerce").iloc[0]
        range_result="HIT" if pd.notna(lo) and pd.notna(hi) and float(lo)<=actual<=float(hi) else "MISS"
        direction="Podstřeleno" if err>0 else ("Přestřeleno" if err<0 else "Přesně")

        log.at[idx,"actual_value"]=actual
        log.at[idx,"result"]=result
        log.at[idx,"range_result"]=range_result
        log.at[idx,"error"]=err
        log.at[idx,"abs_error"]=abs(err)
        log.at[idx,"bias_direction"]=direction
        log.at[idx,"status"]="settled"
        log.at[idx,"settled_at"]=now
        count+=1

    if count or enriched:
        _save_log(log,"stats: settle model predictions" if count else "stats: add prediction ranges")
    return {"settled":count, "ranges_enriched":int(enriched)}

def summary(log=None):
    if log is None:
        log=load_log()
    s=log[log.status.eq("settled")].copy()
    if s.empty:
        return {"n":0,"range_hit_rate":np.nan,"avg_range_width":np.nan,"mae":np.nan,"bias":np.nan,
                "under_rate":np.nan,"over_rate":np.nan}
    err=pd.to_numeric(s.error,errors="coerce")
    lo=pd.to_numeric(s.range_low,errors="coerce"); hi=pd.to_numeric(s.range_high,errors="coerce")
    width=hi-lo+1
    valid=s.range_result.isin(["HIT","MISS"])
    return {
        "n":len(s),
        "range_hit_rate":(s.loc[valid,"range_result"]=="HIT").mean() if valid.any() else np.nan,
        "avg_range_width":width.mean(),
        "mae":pd.to_numeric(s.abs_error,errors="coerce").mean(),
        "bias":err.mean(),
        "under_rate":(err>0).mean(),
        "over_rate":(err<0).mean(),
    }

if __name__=="__main__":
    result=settle()

    # Reload the LOCAL file written by settle(), not a remote copy. This makes
    # GitHub Actions verification deterministic even when no persistence token
    # is available in the runner.
    if LOG_PATH.exists():
        verify=pd.read_csv(LOG_PATH)
    else:
        verify=pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in verify.columns:
            verify[c]=np.nan

    pending=verify[verify["status"].fillna("").astype(str).eq("pending")].copy()
    missing_ranges=0
    if len(pending):
        missing_ranges=int(
            pending[["range_low","range_high","range_probability"]]
            .isna().any(axis=1).sum()
        )

    print(json.dumps(result,indent=2,ensure_ascii=False))
    print(f"Prediction ranges: enriched {int(result.get('ranges_enriched',0))} existing rows")
    print(f"Model prediction log: {len(verify)} rows")
    print(f"Missing ranges: {missing_ranges}")

    if missing_ranges:
        raise SystemExit(
            f"Range migration failed: {missing_ranges} pending model predictions still have no range."
        )
