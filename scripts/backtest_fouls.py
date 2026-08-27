import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, brier_score_loss
from fouls_common import BASE, load_config, load_data, make_model, baseline_prediction, ensemble_prediction, over_probability

REPORTS = BASE / "reports"
REPORTS.mkdir(exist_ok=True)


def main():
    cfg = load_config()
    df = load_data()
    target = cfg["target"]
    seasons = sorted(df["season"].unique())
    folds = seasons[1:]
    rows, preds = [], []

    for test_season in folds:
        train = df[df["season"] < test_season]
        test = df[df["season"] == test_season]
        if train.empty or test.empty:
            continue
        model = make_model(cfg)
        model.fit(train[cfg["features"]], train[target])
        ens, extra, base = ensemble_prediction(model, test, train[target].mean(), cfg)

        for name, p in [("baseline", base), ("extra_trees", extra), ("ensemble", ens)]:
            rows.append({
                "test_season": test_season,
                "n": len(test),
                "model": name,
                "mae": mean_absolute_error(test[target], p),
                "rmse": mean_squared_error(test[target], p) ** 0.5,
                "bias": float(np.mean(p - test[target].to_numpy())),
            })

        fold = test[["match_id","season","match_date","team","opponent","venue",target]].copy()
        fold["predicted_fouls"] = ens
        fold["baseline_fouls"] = base
        fold["extra_trees_fouls"] = extra
        for line in cfg["over_lines"]:
            key = str(line).replace(".", "_")
            fold[f"p_over_{key}"] = over_probability(ens, line)
            fold[f"actual_over_{key}"] = (fold[target] > line).astype(int)
        preds.append(fold)

    metrics = pd.DataFrame(rows)
    oof = pd.concat(preds, ignore_index=True)

    # Main validation excludes tiny current partial season from the aggregate.
    full_seasons = [s for s in folds if len(df[df["season"] == s]) >= 700]
    main = metrics[(metrics.model == "ensemble") & metrics.test_season.isin(full_seasons)]
    baseline = metrics[(metrics.model == "baseline") & metrics.test_season.isin(full_seasons)]

    brier_rows=[]
    main_oof=oof[oof.season.isin(full_seasons)]
    for line in cfg["over_lines"]:
        key=str(line).replace(".","_")
        brier_rows.append({
            "line":line,
            "n":len(main_oof),
            "brier":brier_score_loss(main_oof[f"actual_over_{key}"],main_oof[f"p_over_{key}"])
        })
    brier=pd.DataFrame(brier_rows)

    # Calibration across all configured over lines.
    ps=[]; ys=[]
    for line in cfg["over_lines"]:
        key=str(line).replace(".","_")
        ps.extend(main_oof[f"p_over_{key}"].tolist())
        ys.extend(main_oof[f"actual_over_{key}"].tolist())
    cal=pd.DataFrame({"probability":ps,"actual":ys})
    cal["bin"]=pd.cut(cal.probability,np.linspace(0,1,11),include_lowest=True)
    calibration=cal.groupby("bin",observed=True).agg(n=("actual","size"),predicted=("probability","mean"),actual=("actual","mean")).reset_index()
    calibration["bin"]=calibration["bin"].astype(str)

    metrics.to_csv(REPORTS/"fouls_backtest_by_season.csv",index=False)
    oof.to_csv(REPORTS/"fouls_oof_predictions.csv",index=False)
    brier.to_csv(REPORTS/"fouls_brier_by_line.csv",index=False)
    calibration.to_csv(REPORTS/"fouls_calibration.csv",index=False)

    summary={
      "model_version":cfg["version"],
      "validation_full_seasons":full_seasons,
      "ensemble_mae":float(main.mae.mean()),
      "ensemble_rmse":float(main.rmse.mean()),
      "baseline_mae":float(baseline.mae.mean()),
      "mae_improvement_vs_baseline":float(baseline.mae.mean()-main.mae.mean()),
      "avg_brier":float(brier.brier.mean()),
      "notes":"Walk-forward by season. Each test season is predicted only from earlier seasons. 2026-27 is reported separately as provisional due to sample size."
    }
    (REPORTS/"fouls_backtest_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print("\n",metrics.to_string(index=False))

if __name__ == "__main__":
    main()
