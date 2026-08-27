import json
from datetime import datetime
import joblib
from fouls_common import BASE, MODEL_PATH, load_config, load_data, make_model


def main():
    cfg=load_config(); df=load_data(); target=cfg["target"]
    model=make_model(cfg)
    model.fit(df[cfg["features"]],df[target])
    artifact={
      "model":model,
      "config":cfg,
      "train_mean":float(df[target].mean()),
      "trained_rows":int(len(df)),
      "seasons":sorted(df.season.unique().tolist()),
      "trained_at":datetime.now().isoformat(timespec="seconds")
    }
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(artifact,MODEL_PATH)
    meta={k:v for k,v in artifact.items() if k!="model"}
    (MODEL_PATH.parent/"fouls_model_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    print(json.dumps(meta,indent=2))

if __name__=="__main__": main()
