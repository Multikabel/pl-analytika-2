from pathlib import Path
import subprocess, sys

BASE=Path(__file__).resolve().parent.parent

def run(args, required=True):
    print("\n>>>", " ".join(map(str,args)), flush=True)
    p=subprocess.run(args,cwd=BASE)
    if required and p.returncode:
        raise SystemExit(p.returncode)
    return p.returncode

def main():
    py=sys.executable

    # Fixture/official sync should not block match-result settlement if PL site changes temporarily.
    run([py,"scripts/update_fixtures.py","--season","2026-27","--force"], required=False)

    # Results and generated feature tables.
    run([py,"scripts/update_data.py","--download-current"])

    # Settle tips against the freshly rebuilt team_match_stats.
    run([py,"scripts/prediction_archive.py"])

    # Train models on all currently completed matches.
    run([py,"scripts/train_count_models.py"])

    # Snapshot the next/current unplayed round. Duplicate prediction IDs are ignored.
    run([py,"scripts/snapshot_next_round.py"])

    print("\nAutomatic update completed.")

if __name__=="__main__":
    main()
