import argparse
import joblib
import pandas as pd
from fouls_common import DATA_PATH, MODEL_PATH, ensemble_prediction, over_probability


def main():
    p=argparse.ArgumentParser(description="Score existing pre-match feature rows for team fouls")
    p.add_argument("--input",default=str(DATA_PATH))
    p.add_argument("--output",default="")
    args=p.parse_args()
    artifact=joblib.load(MODEL_PATH)
    cfg=artifact["config"]; df=pd.read_csv(args.input)
    pred,extra,base=ensemble_prediction(artifact["model"],df,artifact["train_mean"],cfg)
    keep=[c for c in ["match_id","season","match_date","team","opponent","venue","referee"] if c in df.columns]
    out=df[keep].copy(); out["predicted_fouls"]=pred
    for line in cfg["over_lines"]:
        out[f"p_over_{str(line).replace('.', '_')}"]=over_probability(pred,line)
    path=args.output or "fouls_predictions.csv"
    out.to_csv(path,index=False)
    print(path)

if __name__=="__main__": main()
