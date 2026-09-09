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
    # Schedule is required for correct current-round identity.
    run([py,"scripts/update_fixtures.py","--season","2026-27","--force"], required=True)
    # Results are critical: never report a green workflow with stale cached results.
    run([py,"scripts/update_data.py","--download-current"], required=True)
    # Officials may legitimately not be published yet, so this one is non-fatal.
    run([py,"scripts/update_officials.py","--force"], required=False)
    # Settlement is critical. If either fails, the workflow must be red.
    run([py,"scripts/prediction_archive.py"], required=True)
    run([py,"scripts/model_prediction_stats.py"], required=True)
    run([py,"scripts/train_count_models.py"], required=True)
    run([py,"scripts/snapshot_model_predictions.py"], required=True)
    print("\nAutomatic update completed successfully.")

if __name__=="__main__": main()
