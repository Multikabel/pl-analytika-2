from pathlib import Path
import argparse
import joblib
import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom

from count_common import MODELS_DIR, load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows

MARKETS=("fouls","corners","yellow_cards")
MARKET_LABEL={"fouls":"Fauly","corners":"Rohy","yellow_cards":"ŽK",
              "fouls_total":"Fauly celkem","corners_total":"Rohy celkem",
              "yellow_cards_total":"Karty celkem"}

def _total_over_probability(mu_home,mu_away,line,cfg):
    """Moment-matched distribution for the sum of the two team count distributions."""
    mu=max(float(mu_home)+float(mu_away),0.05)
    k=int(np.floor(float(line)))
    dist=cfg.get("distribution",{"type":"poisson"})
    if dist.get("type")=="negative_binomial":
        alpha=float(dist["alpha"])
        # Team NB variance = mu + alpha*mu^2. Independent sum variance is additive.
        var=mu_home + alpha*mu_home**2 + mu_away + alpha*mu_away**2
        if var>mu:
            alpha_total=(var-mu)/(mu**2)
            n=1.0/alpha_total
            p=n/(n+mu)
            return float(nbinom.sf(k,n,p))
    return float(poisson.sf(k,mu))

def _total_lines(mu):
    # Half-lines centered around the predicted match total.
    center=int(np.floor(mu))
    lo=max(0,center-8)
    hi=center+9
    return [x+0.5 for x in range(lo,hi)]

def score_fixture(home,away,date,season,referee=""):
    fixture=build_fixture_rows(home,away,referee,date,season)
    records=[]
    for market in MARKETS:
        path=MODELS_DIR/f"{market}_model.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Missing model: {path}")
        art=joblib.load(path); cfg=art["config"]
        for c in cfg["features"]:
            if c not in fixture.columns:
                fixture[c]=np.nan
        pred,extra,baseline=ensemble_prediction(
            art["model"],fixture,art["train_mean"],cfg
        )

        # Team markets.
        for i,row in fixture.iterrows():
            for line in cfg["over_lines"]:
                p=float(over_probability([pred[i]],line,cfg)[0])
                records.append({
                    "match_date":date,"season":season,"home_team":home,"away_team":away,
                    "referee":referee,"team":row["team"],"venue":row["venue"],
                    "market":market,"market_label":MARKET_LABEL[market],
                    "line":float(line),"prediction":float(pred[i]),
                    "model_component":float(extra[i]),"baseline_component":float(baseline[i]),
                    "p_over":p,"p_under":1-p,
                    "fair_over":float(fair_odds([p])[0]),
                    "fair_under":float(fair_odds([1-p])[0]),
                })

        # Match-total market. The total probability is derived from the sum distribution,
        # not by adding team probabilities.
        total_market=f"{market}_total"
        mu_home=float(pred[0]); mu_away=float(pred[1]); mu_total=mu_home+mu_away
        for line in _total_lines(mu_total):
            p=_total_over_probability(mu_home,mu_away,line,cfg)
            records.append({
                "match_date":date,"season":season,"home_team":home,"away_team":away,
                "referee":referee,"team":"CELKEM","venue":"T",
                "market":total_market,"market_label":MARKET_LABEL[total_market],
                "line":float(line),"prediction":float(mu_total),
                "model_component":float(extra[0]+extra[1]),
                "baseline_component":float(baseline[0]+baseline[1]),
                "p_over":p,"p_under":1-p,
                "fair_over":float(fair_odds([p])[0]),
                "fair_under":float(fair_odds([1-p])[0]),
            })
    return pd.DataFrame(records)

def score_fixtures(fixtures):
    out=[]
    for fx in fixtures:
        out.append(score_fixture(
            fx["home_team"],fx["away_team"],fx["match_date"],fx["season"],fx.get("referee","")
        ))
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--fixtures",required=True,help="CSV: home_team,away_team,match_date,season,referee")
    p.add_argument("--output",default="reports/round_predictions.csv")
    args=p.parse_args()
    fixtures=pd.read_csv(args.fixtures).fillna("")
    required={"home_team","away_team","match_date","season"}
    missing=required-set(fixtures.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    out=score_fixtures(fixtures.to_dict("records"))
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(path,index=False,encoding="utf-8-sig")
    print(path)

if __name__=="__main__":
    main()
