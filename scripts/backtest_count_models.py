import json
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, brier_score_loss
from count_common import BASE, load_config, load_data, make_model, ensemble_prediction, over_probability

MARKETS=("fouls","corners","yellow_cards")
TEST_SEASONS=("2023-24","2024-25","2025-26")

def main():
    df=load_data()
    out={}
    rows=[]
    for market in MARKETS:
        cfg=load_config(market); target=cfg["target"]
        all_y=[]; all_pred=[]
        season_rows=[]
        for season in TEST_SEASONS:
            train=df[(df["season"]<season)&df[target].notna()].copy()
            test=df[(df["season"]==season)&df[target].notna()].copy()
            model=make_model(cfg); model.fit(train[cfg["features"]],train[target])
            pred,extra,base=ensemble_prediction(model,test,float(train[target].mean()),cfg)
            y=test[target].to_numpy(dtype=float)
            row={
                "market":market,"season":season,"n":len(test),
                "mae":mean_absolute_error(y,pred),
                "rmse":mean_squared_error(y,pred)**0.5,
                "baseline_mae":mean_absolute_error(y,base),
                "extra_trees_mae":mean_absolute_error(y,extra)
            }
            rows.append(row); season_rows.append(row)
            all_y.extend(y); all_pred.extend(pred)
        y=np.asarray(all_y); pred=np.asarray(all_pred)
        briers=[]
        for line in cfg["over_lines"]:
            p=over_probability(pred,line,cfg)
            hit=(y>line).astype(int)
            briers.append(float(brier_score_loss(hit,p)))
        out[market]={
            "n":len(y),
            "mae":float(mean_absolute_error(y,pred)),
            "rmse":float(mean_squared_error(y,pred)**0.5),
            "mean_brier":float(np.mean(briers)),
            "distribution":cfg["distribution"],
            "by_season":season_rows
        }
    report_dir=BASE/"reports"; report_dir.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(report_dir/"count_models_backtest.csv",index=False)
    (report_dir/"count_models_backtest.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps(out,indent=2))

if __name__=="__main__":
    main()
