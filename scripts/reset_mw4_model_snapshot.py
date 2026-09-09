from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "predictions" / "model_prediction_log.csv"
BACKUP = ROOT / "data" / "predictions" / "model_prediction_log.before_mw4_reset.csv"

TARGET_SEASON = "2026-27"
TARGET_ROUND = 4

if not LOG.exists():
    raise SystemExit(f"Missing {LOG}")

df = pd.read_csv(LOG)
if df.empty:
    print("Model prediction log is already empty; nothing to reset.")
    raise SystemExit(0)

# Keep an exact local backup before touching anything.
df.to_csv(BACKUP, index=False)

season_col = next((c for c in ["season", "Season"] if c in df.columns), None)
round_col = next((c for c in ["round", "match_round", "MatchRound", "gameweek", "mw"] if c in df.columns), None)

if season_col is None:
    raise SystemExit(f"Cannot safely reset: season column not found. Columns: {list(df.columns)}")

season_mask = df[season_col].astype(str).str.strip().eq(TARGET_SEASON)

if round_col is not None:
    round_num = pd.to_numeric(df[round_col], errors="coerce")
    target = season_mask & round_num.eq(TARGET_ROUND)
else:
    # Current repository state has exactly one archived batch for 2026-27: MW4.
    # Refuse to act unless it is exactly the expected 90 rows.
    target = season_mask
    if int(target.sum()) != 90:
        raise SystemExit(
            f"Safety stop: no round column and found {int(target.sum())} rows for "
            f"{TARGET_SEASON}, expected exactly 90."
        )

n = int(target.sum())
if n != 90:
    raise SystemExit(
        f"Safety stop: found {n} MW4 model rows, expected exactly 90. "
        "No rows were changed."
    )

clean = df.loc[~target].copy()
clean.to_csv(LOG, index=False)

print(f"Removed exactly {n} model prediction rows for {TARGET_SEASON} MW{TARGET_ROUND}.")
print(f"Remaining model prediction rows: {len(clean)}")
print(f"Backup: {BACKUP}")
print("Now recalculate the whole MW4 once in the app with the corrected referees.")
