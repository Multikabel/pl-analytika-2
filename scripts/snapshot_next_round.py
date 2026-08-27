from pathlib import Path
import pandas as pd

from update_fixtures import load_fixtures, current_round
from update_officials import sync_officials, referee_for_match
from score_round import score_fixtures
from prediction_archive import archive_predictions

BASE=Path(__file__).resolve().parent.parent
TABLES=BASE/"data"/"tables"

def main():
    tm=pd.read_csv(TABLES/"team_match_stats.csv")
    season=sorted(tm["season"].dropna().astype(str).unique())[-1]
    completed=tm[(tm.season==season)&(tm.venue=="H")][["team","opponent"]].rename(
        columns={"team":"home_team","opponent":"away_team"}
    )
    schedule=load_fixtures(season,auto_sync=True)
    rnd,round_df=current_round(schedule,completed)
    try:
        sync_officials(rnd)
    except Exception:
        pass

    future=round_df[~round_df["played"]].copy()
    if future.empty:
        print("No unplayed fixtures to snapshot.")
        return

    fixtures=[]
    for _,r in future.iterrows():
        fixtures.append({
            "home_team":r.home_team,
            "away_team":r.away_team,
            "match_date":r.match_date,
            "season":season,
            "referee":referee_for_match(r.home_team,r.away_team,rnd),
        })

    scored=score_fixtures(fixtures)
    added=archive_predictions(
        scored,
        match_round=rnd,
        min_fair=2.0,
        model_version="count-models-v0.2",
    )
    print(f"Match Round {rnd}: archived {added} new tips.")

if __name__=="__main__":
    main()
