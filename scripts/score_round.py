from pathlib import Path
import argparse
import joblib
import numpy as np
import pandas as pd

from count_common import MODELS_DIR, load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows

MARKETS=("fouls","corners","yellow_cards")
MARKET_LABEL={"fouls":"Fauly","corners":"Rohy","yellow_cards":"ŽK"}

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
        for i,row in fixture.iterrows():
            for line in cfg["over_lines"]:
                p=float(over_probability([pred[i]],line,cfg)[0])
                records.append({
                    "match_date":date,
                    "season":season,
                    "home_team":home,
                    "away_team":away,
                    "referee":referee,
                    "team":row["team"],
                    "venue":row["venue"],
                    "market":market,
                    "market_label":MARKET_LABEL[market],
                    "line":float(line),
                    "prediction":float(pred[i]),
                    "model_component":float(extra[i]),
                    "baseline_component":float(baseline[i]),
                    "p_over":p,
                    "p_under":1-p,
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
