# Predikce budoucího zápasu

Po aktualizaci dat a natrénování modelů:

```bash
python scripts/predict_match.py ^
  --home "Arsenal" ^
  --away "Coventry" ^
  --date 2026-08-21 ^
  --season 2026-27 ^
  --referee "Michael Oliver"
```

Skript vytvoří pro oba týmy:

- očekávané fauly,
- očekávané rohy,
- očekávané ŽK,
- pravděpodobnosti Over i Under pro definované hranice,
- fair odds.

Výstup se standardně uloží do:

`reports/upcoming_match_prediction.csv`

Pokud rozhodčí ještě není známý, `--referee` lze vynechat. Chybějící
rozhodcovské feature doplní model přes median imputation.

`fixture_features.py` počítá vstupy pouze z utkání odehraných před
zadaným datem.
