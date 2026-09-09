from pathlib import Path
import subprocess, sys

BASE=Path(__file__).resolve().parent.parent

def run(args, required=True):
    print("\n>>>", " ".join(map(str,args)), flush=True)
    p=subprocess.run(args,cwd=BASE)
    if p.returncode and not required:
        print(f"WARNING: optional step failed with code {p.returncode}; continuing.")
    if required and p.returncode:
        raise SystemExit(p.returncode)
    return p.returncode

def main():
    py=sys.executable
    # External schedule/official feeds must never block result updates.
    run([py,"scripts/update_fixtures.py","--season","2026-27","--force"], required=False)
    run([py,"scripts/update_data.py","--download-current"], required=True)
    run([py,"scripts/update_officials.py","--force"], required=False)

    # Settlement failures are isolated so the rest of the daily refresh still runs.
    run([py,"scripts/prediction_archive.py"], required=False)
    run([py,"scripts/model_prediction_stats.py"], required=False)

    # Rebuild model; if a transient modelling/snapshot issue appears, generated data
    # tables and results are still allowed to be committed.
    run([py,"scripts/train_count_models.py"], required=False)
    run([py,"scripts/snapshot_model_predictions.py"], required=False)
    print("\nAutomatic update completed.")

if __name__=="__main__": main()
