from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import ExtraTreesRegressor

BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config" / "fouls_model.json"
DATA_PATH = BASE / "data" / "tables" / "pre_match_features.csv"
MODEL_PATH = BASE / "models" / "fouls_model.joblib"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_data():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}. Run scripts/update_data.py first.")
    df = pd.read_csv(DATA_PATH)
    return df[df["target_fouls_committed"].notna()].copy()


def make_model(cfg):
    p = cfg["extra_trees"]
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("model", ExtraTreesRegressor(**p)),
    ])


def baseline_prediction(df, train_mean):
    a = df["season_fouls_committed_avg"].combine_first(df["pl_last5_fouls_committed_avg"])
    b = df["opp_season_fouls_suffered_avg"].combine_first(df["opp_pl_last5_fouls_suffered_avg"])
    pred = (a + b) / 2.0
    side = pd.Series(
        np.where(df["venue"].eq("H"), df["home_fouls_avg_before"], df["away_fouls_avg_before"]),
        index=df.index,
    )
    pred = pred.fillna(side)
    pred = pred.fillna(df["league_total_fouls_avg_before"] / 2.0)
    pred = pred.fillna(float(train_mean))
    return pred.to_numpy(dtype=float)


def ensemble_prediction(model, df, train_mean, cfg):
    features = cfg["features"]
    extra = model.predict(df[features])
    base = baseline_prediction(df, train_mean)
    w = cfg["ensemble"]["extra_trees_weight"]
    pred = w * extra + (1.0 - w) * base
    return np.clip(pred, 0.1, None), extra, base


def over_probability(mean_fouls, line):
    return poisson.sf(int(np.floor(line)), np.clip(mean_fouls, 0.1, None))
