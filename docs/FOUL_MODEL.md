# Foul model v0.1

## Goal
Predict team fouls committed before kickoff and derive over-line probabilities.

## Point prediction
The final expected value is an ensemble:

- 70% ExtraTrees regressor
- 30% transparent baseline blending the team's own foul rate and the opponent's fouls-suffered rate

Only 32 foul-relevant pre-match features are used. The model deliberately does not ingest all available columns.

## Validation
Walk-forward by season. A season is tested only after fitting on all earlier seasons. The main validation set is 2023-24, 2024-25 and 2025-26. The partial 2026-27 season is displayed separately and is not used for headline metrics.

## Probabilities
Over probabilities use a Poisson count distribution with the ensemble prediction as its mean. Historical variance of team foul counts is close to the mean, and walk-forward calibration is strong.

## Commands
```bash
python scripts/backtest_fouls.py
python scripts/train_fouls_model.py
```
