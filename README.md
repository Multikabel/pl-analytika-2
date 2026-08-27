# PL Analytika 2.0 – datová vrstva 2.0

Kompletní datová vrstva před stavbou predikčního modelu. Zdrojové historické zápasy jsou z `football-data.co.uk` (`E0.csv`).

## Co pipeline dělá

- importuje a normalizuje sezónní CSV,
- ignoruje neodehrané řádky bez výsledku, aby nekontaminovaly statistiky,
- sjednocuje názvy týmů,
- ukládá match-level a team-level historii,
- zachovává dostupné bookmaker kurzy v `match_odds`,
- vytváří season, home/away, rolling, distribution a threshold tabulky,
- vytváří historii rozhodčích,
- vytváří tabulku ligy po každém hracím dni,
- vytváří leakage-safe `pre_match_features`,
- vytváří dashboardové tabulky pro aktuální sezónu,
- provádí kontrolu kvality a ukládá ji do `data_quality_report`.

## Struktura

```text
pl-analytika-2/
├── database/
│   └── schema.sql
├── scripts/
│   └── update_data.py
├── docs/
│   ├── DATA_DICTIONARY.md
│   └── FEATURE_DICTIONARY.csv
├── data/
│   ├── raw/
│   └── tables/
├── update_data.bat
├── update_local_only.bat
├── requirements.txt
├── .gitignore
└── README.md
```

## První spuštění

Do `data/raw/` vlož historické soubory například `2022-23.csv` až `2026-27.csv`.

```bash
pip install -r requirements.txt
python scripts/update_data.py
```

## Aktualizace po hracím dni

Ve Windows stačí spustit:

```text
update_data.bat
```

To stáhne aktuální `E0.csv` a znovu bezpečně přepočítá datovou vrstvu. Alternativně:

```bash
python scripts/update_data.py --download-current
```

Pokud si CSV aktualizuješ ručně, použij `update_local_only.bat`.

## Pre-match modelová tabulka

`pre_match_features` má aktuálně **295 sloupců**, z toho **139 soupeřových pre-match metrik** a **10 explicitně oddělených target sloupců**.

Obsahuje mimo jiné:

- sezónní profil týmu,
- home/away profil,
- Last 3 / Last 5 / Last 10,
- mezi-sezónní PL Last 5,
- stejnou sadu informací pro soupeře,
- tabulkovou pozici, body, PPG a goal difference před zápasem,
- dny odpočinku,
- sezónní i mezi-sezónní historii rozhodčího,
- ligové tempo a recent league tempo,
- H2H historii,
- cílové skutečné hodnoty oddělené prefixem `target_`.

## Ověřený build

Na dodaných 5 sezónách:

- zápasy: **1530**
- team-match řádky: **3060**
- pre-match řádky: **3060**
- match context řádky: **1530**
- bookmaker hodnoty: **134139**

Kontrola byla spuštěna opakovaně bez vzniku duplicit.
