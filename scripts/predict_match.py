import argparse
import json
import joblib
import pandas as pd
from count_common import MODELS_DIR, load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows

MARKETS=("fouls","corners","yellow_cards")

def main():
    p=argparse.ArgumentParser(description="Predict team counts for an upcoming Premier League match.")
    p.add_argument("--home",required=True)
    p.add_argument("--away",required=True)
    p.add_argument("--date",required=True,help="YYYY-MM-DD")
    p.add_argument("--season",required=True,help="e.g. 2026-27")
    p.add_argument("--referee",default="")
    p.add_argument("--output",default="reports/upcoming_match_prediction.csv")
    args=p.parse_args()

    fixture=build_fixture_rows(args.home,args.away,args.referee,args.date,args.season)
    outputs=[]
    for market in MARKETS:
        path=MODELS_DIR/f"{market}_model.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run scripts/train_count_models.py.")
        artifact=joblib.load(path)
        cfg=artifact["config"]
        # Add missing optional feature columns as NaN; model imputer handles early-season gaps.
        for c in cfg["features"]:
            if c not in fixture: fixture[c]=float("nan")
        pred,extra,base=ensemble_prediction(
            artifact["model"],fixture,artifact["train_mean"],cfg
        )
        for i,row in fixture.iterrows():
            rec={
                "match_date":args.date,"season":args.season,"home_team":args.home,
                "away_team":args.away,"referee":args.referee,
                "team":row["team"],"venue":row["venue"],"market":market,
                "prediction":round(float(pred[i]),3),
                "model_component":round(float(extra[i]),3),
                "baseline_component":round(float(base[i]),3)
            }
            for line in cfg["over_lines"]:
                po=float(over_probability([pred[i]],line,cfg)[0])
                pu=1-po
                key=str(line).replace(".","_")
                rec[f"p_over_{key}"]=round(po,5)
                rec[f"fair_over_{key}"]=round(float(fair_odds([po])[0]),3)
                rec[f"p_under_{key}"]=round(pu,5)
                rec[f"fair_under_{key}"]=round(float(fair_odds([pu])[0]),3)
            outputs.append(rec)

    out=pd.DataFrame(outputs)
    out_path=__import__("pathlib").Path(args.output)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(out_path,index=False,encoding="utf-8-sig")

    print(f"\n{args.home} vs {args.away} | {args.date} | referee: {args.referee or 'unknown'}")
    for team in (args.home,args.away):
        print(f"\n{team}")
        for market in MARKETS:
            r=out[(out.team==team)&(out.market==market)].iloc[0]
            print(f"  {market:13s}: {r.prediction:.2f}")
            cfg=load_config(market)
            bits=[]
            for line in cfg["over_lines"]:
                k=str(line).replace(".","_")
                bits.append(f"O{line}: {100*r[f'p_over_{k}']:.1f}% (fair {r[f'fair_over_{k}']:.2f})")
            print("    "+" | ".join(bits))
    print(f"\nSaved: {out_path}")

if __name__=="__main__":
    main()
