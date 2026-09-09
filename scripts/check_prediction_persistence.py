from pathlib import Path
import pandas as pd
from github_persistence import enabled, read_csv

for path in ["data/predictions/prediction_log.csv","data/predictions/model_prediction_log.csv"]:
    local=Path(__file__).resolve().parent.parent/path
    local_n=max(0,len(pd.read_csv(local))) if local.exists() else -1
    remote_n="disabled"
    if enabled():
        try:
            remote,_=read_csv(path)
            remote_n=len(remote) if remote is not None else -1
        except Exception as e:
            remote_n=f"ERROR: {e}"
    print(f"{path}: local={local_n}, github={remote_n}")
