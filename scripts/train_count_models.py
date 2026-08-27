from datetime import datetime
import json
import joblib
from count_common import MODELS_DIR, load_config, load_data, make_model

MARKETS=("fouls","corners","yellow_cards")

def main():
    df=load_data()
    MODELS_DIR.mkdir(exist_ok=True)
    for market in MARKETS:
        cfg=load_config(market)
        target=cfg["target"]
        train=df[df[target].notna()].copy()
        model=make_model(cfg)
        model.fit(train[cfg["features"]],train[target])
        artifact={
            "market":market,"model":model,"config":cfg,
            "train_mean":float(train[target].mean()),
            "trained_rows":int(len(train)),
            "seasons":sorted(train["season"].dropna().unique().tolist()),
            "trained_at":datetime.now().isoformat(timespec="seconds")
        }
        path=MODELS_DIR/f"{market}_model.joblib"
        joblib.dump(artifact,path)
        meta={k:v for k,v in artifact.items() if k!="model"}
        (MODELS_DIR/f"{market}_model_metadata.json").write_text(
            json.dumps(meta,indent=2),encoding="utf-8"
        )
        print(f"{market}: {len(train)} rows -> {path}")

if __name__=="__main__":
    main()
