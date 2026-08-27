# PL Analytika 2.0

Datová a modelová vrstva pro Premier League analytiku.

## Aktuální stav

Datová pipeline:
- 5 sezon
- 1 530 zápasů
- 3 060 team-match řádků
- 295 leakage-safe pre-match sloupců
- týmové, soupeřovy, home/away, rolling, referee, league a H2H statistiky

Modely:
- fauly
- rohy
- žluté karty

## Instalace

```bash
pip install -r requirements.txt
```

## Aktualizace dat

```bash
python scripts/update_data.py --download-current
```

Ve Windows lze spustit `update_data.bat`.

## Aktualizace + trénink všech modelů

```text
update_and_train.bat
```

nebo:

```bash
python scripts/update_data.py --download-current
python scripts/train_count_models.py
```

## Predikce konkrétního zápasu

```bash
python scripts/predict_match.py --home "Arsenal" --away "Coventry" --date 2026-08-21 --season 2026-27 --referee "Michael Oliver"
```

Výstup:
- očekávaný počet,
- Over/Under pravděpodobnosti,
- fair odds,
- CSV do `reports/`.

## Modelová metodika

Viz:
- `docs/COUNT_MODELS_V0_2.md`
- `docs/PREDICT_MATCH.md`
- `docs/FOUL_MODEL.md`
- `docs/FOUL_BACKTEST_V0_1.md`

## Git

RAW CSV, generované tabulky, reporty a `.joblib` modely zůstávají lokálně
a nejsou ukládány do GitHubu.


## Tabulkové UI v0.3

Spuštění:

```text
run_app.bat
```

První kompletní setup:

```text
setup_and_run.bat
```

Streamlit aplikace je v `app/app.py`. Obsahuje hustou tabulku týmových statistik a prediktor zápasu pro fauly, rohy a ŽK včetně O/U pravděpodobností a fair odds.
