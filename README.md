# PL Analytika 2.0

Datová vrstva pro analytickou aplikaci Premier League.

## Struktura

```text
pl-analytika-2/
├── database/
│   └── schema.sql
├── scripts/
│   └── update_data.py
├── data/
│   ├── raw/
│   └── tables/
├── .gitignore
├── requirements.txt
└── README.md
```

RAW CSV, generované tabulky a SQLite databáze nejsou verzovány v GitHubu.

## Lokální data

Do `data/raw/` vlož:

- `2022-23.csv`
- `2023-24.csv`
- `2024-25.csv`
- `2025-26.csv`
- `2026-27.csv`

## Instalace

```bash
pip install -r requirements.txt
```

## Aktualizace z lokálních CSV

```bash
python scripts/update_data.py
```

## Aktualizace aktuální sezóny z football-data.co.uk

```bash
python scripts/update_data.py --download-current
```

Skript aktualizuje SQLite databázi a exportuje datové tabulky do `data/tables/`.

## Aktuální datové tabulky

- matches
- team_match_stats
- match_odds
- teams
- team_name_mapping
- referees
- referee_match_stats
- team_season_stats
- team_home_away_stats
- team_form_stats
- referee_season_stats
- referee_form_stats
- league_stats
- standings_history
- data_sources
- update_log

Predikční model zatím není součástí této verze.
