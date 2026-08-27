# PL Analytika 2.0 – datová vrstva

Tato verze záměrně neobsahuje predikční model. Nejdřív buduje čistou a opakovatelně aktualizovatelnou datovou základnu.

## Vstupy
`data/raw/2022-23.csv` až `data/raw/2026-27.csv`

## Hlavní tabulky
- `matches` – 1 řádek = zápas
- `team_match_stats` – 2 řádky = pohled domácího a hostujícího týmu
- `match_odds` – všechny ostatní numerické sloupce ze zdrojového CSV v dlouhém formátu
- `referee_match_stats` – rozhodčí po jednotlivých zápasech
- `teams`, `referees`, `team_name_mapping` – číselníky
- `team_season_stats` – sezónní týmové souhrny
- `team_home_away_stats` – home/away souhrny
- `team_form_stats` – poslední 3/5/10 k jednotlivým hracím dnům
- `referee_season_stats` – sezónní souhrny rozhodčích
- `referee_form_stats` – poslední 3/5/10 k jednotlivým hracím dnům
- `league_stats` – ligové referenční hodnoty
- `standings_history` – tabulka PL po každém hracím datu
- `update_log`, `data_sources` – audit aktualizací

## xG
`HxG/AxG` je volitelné. Starší sezóny mají `NULL`, 2026/27 se plní automaticky, pokud sloupce existují.

## První spuštění
```bash
pip install -r requirements.txt
python update_data.py
```

## Aktualizace po hracím dni
Nejjednodušší varianta:
```bash
python update_data.py --download-current
```

Skript stáhne aktuální `E0.csv`, přepíše aktuální sezonní CSV, znovu provede idempotentní import a přepočítá odvozené datové tabulky. Historie zápasů se neduplikuje díky stabilnímu `match_id`.

Pokud si CSV stahuješ ručně, stačí nahradit `data/raw/2026-27.csv` novější verzí a spustit:
```bash
python update_data.py
```

## Výstupy
SQLite:
`data/pl_analytika.sqlite`

CSV export každé tabulky:
`data/tables/*.csv`

## Poznámka k form tabulkám
`team_form_stats` a `referee_form_stats` jsou datové agregace, nikoli predikce. Jsou připraveny pro budoucí model. Aktuálně používají stav **včetně zápasů daného data**; pro budoucí backtest vytvoříme zvlášť leakage-safe pre-match features.
