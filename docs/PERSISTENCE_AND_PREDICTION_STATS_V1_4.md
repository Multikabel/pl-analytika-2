# v1.4 – persistent tips + prediction accuracy

## 1. Persistent manual tips

Streamlit Community Cloud filesystem is ephemeral. A tip written only to
`data/predictions/prediction_log.csv` can disappear after app restart.

v1.4 optionally writes the log directly to the GitHub repository through
the GitHub Contents API.

Configure Streamlit Secrets:

```toml
[github]
token = "github_pat_..."
repo = "Multikabel/pl-analytika-2"
branch = "main"
```

The token should be a fine-grained GitHub Personal Access Token restricted
to this repository with **Contents: Read and write** permission.

Never commit the real token to GitHub.

## 2. Prediction accuracy

GitHub Actions automatically saves one point prediction per match/team/market.

Audit line:
`ceil(prediction) - 0.5`

Examples:
- 21.8 -> Over 21.5
- 21.2 -> Over 20.5
- 21.0 -> Over 20.5

After the match it records:
- HIT / MISS of that Over line,
- actual count,
- signed error = actual - prediction,
- absolute error,
- Podstřeleno / Přestřeleno.

The new **Statistiky** page shows:
- Over hit rate,
- MAE,
- mean bias,
- underprediction share,
- overprediction share,
- breakdown by all six markets.
