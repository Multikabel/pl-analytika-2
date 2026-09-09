from pathlib import Path
import subprocess, sys
import pandas as pd

BASE=Path(__file__).resolve().parent.parent

def run(args, required=True):
    print("\n>>>", " ".join(map(str,args)), flush=True)
    p=subprocess.run(args,cwd=BASE)
    if p.returncode and not required:
        print(f"WARNING: optional step failed with code {p.returncode}; continuing.")
    if required and p.returncode:
        raise SystemExit(p.returncode)
    return p.returncode

def validate_current_state():
    fixtures=pd.read_csv(BASE/"data/fixtures/premier_league_2026-27.csv")
    tm=pd.read_csv(BASE/"data/tables/team_match_stats.csv")
    cur=tm[tm.season.astype(str)=="2026-27"].copy()
    home=cur[cur.venue.astype(str)=="H"]
    schedule_teams=set(fixtures.home_team.astype(str)) | set(fixtures.away_team.astype(str))
    data_teams=set(cur.team.astype(str))
    unknown=sorted(data_teams-schedule_teams)
    if unknown:
        raise SystemExit(f"Current data contains teams outside fixture schedule: {unknown}")
    if len(data_teams)!=20:
        raise SystemExit(f"Expected 20 current-season teams, got {len(data_teams)}: {sorted(data_teams)}")
    if home.duplicated(["team","opponent"]).any():
        raise SystemExit("Duplicate current-season fixtures detected in team_match_stats")
    print(f"Validated current state: {len(home)} played matches, 20 teams, no duplicate fixtures.",flush=True)

def main():
    py=sys.executable
    # Schedule is required for correct current-round identity.
    run([py,"scripts/update_fixtures.py","--season","2026-27","--force"], required=True)
    # Results are critical: never report a green workflow with stale cached results.
    run([py,"scripts/update_data.py","--download-current"], required=True)
    validate_current_state()
    # Officials may legitimately not be published yet, so this one is non-fatal.
    run([py,"scripts/update_officials.py","--force"], required=False)
    # Settlement is critical. If either fails, the workflow must be red.
    run([py,"scripts/prediction_archive.py"], required=True)
    run([py,"scripts/model_prediction_stats.py"], required=True)
    run([py,"scripts/train_count_models.py"], required=True)
    run([py,"scripts/snapshot_model_predictions.py"], required=True)
    print("\nAutomatic update completed successfully.")

if __name__=="__main__": main()
