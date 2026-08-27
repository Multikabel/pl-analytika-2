from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import ExtraTreesRegressor

BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data" / "tables" / "pre_match_features.csv"
MODELS_DIR = BASE / "models"

def config_path(market):
    return BASE / "config" / f"{market}_model.json"

def load_config(market):
    return json.loads(config_path(market).read_text(encoding="utf-8"))

def load_data():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}. Run scripts/update_data.py first.")
    return pd.read_csv(DATA_PATH)

def make_model(cfg):
    return Pipeline([
        ("imputer",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",ExtraTreesRegressor(**cfg["extra_trees"]))
    ])

def baseline_prediction(df, train_mean, cfg):
    b=cfg["baseline"]
    a=df[b["for"]]
    if b.get("for_fallback"):
        a=a.combine_first(df[b["for_fallback"]])
    opp=df[b["against"]]
    if b.get("against_fallback"):
        opp=opp.combine_first(df[b["against_fallback"]])
    pred=(a+opp)/2.0
    pred=pred.fillna(df[b["league"]]/2.0)
    pred=pred.fillna(float(train_mean))
    return pred.to_numpy(dtype=float)

def ensemble_prediction(model, df, train_mean, cfg):
    extra=model.predict(df[cfg["features"]])
    base=baseline_prediction(df,train_mean,cfg)
    w=float(cfg["ensemble"]["extra_trees_weight"])
    pred=np.clip(w*extra+(1-w)*base,0.05,None)
    return pred,extra,base

def over_probability(mu,line,cfg):
    mu=np.clip(np.asarray(mu,dtype=float),0.05,None)
    k=int(np.floor(float(line)))
    dist=cfg.get("distribution",{"type":"poisson"})
    if dist["type"]=="negative_binomial":
        alpha=float(dist["alpha"])
        n=1.0/alpha
        p=n/(n+mu)
        return nbinom.sf(k,n,p)
    return poisson.sf(k,mu)

def under_probability(mu,line,cfg):
    return 1.0-over_probability(mu,line,cfg)

def fair_odds(prob):
    p=np.asarray(prob,dtype=float)
    return np.where(p>0,1.0/p,np.inf)
