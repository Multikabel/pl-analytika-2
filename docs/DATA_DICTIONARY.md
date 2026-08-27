# Datový slovník

## CORE

### `matches`
Jeden řádek = jeden dokončený zápas. Obsahuje datum, týmy, rozhodčího a výsledek.

### `team_match_stats`
Jeden řádek = jeden tým v jednom zápase. Každý zápas má dva řádky. Obsahuje `for` i `against` statistiky pro góly, střely, SOT, fauly, rohy, karty a dostupné xG.

### `match_odds`
Dlouhý formát všech ostatních numerických kurzových sloupců dostupných ve zdrojovém CSV.

## TÝMOVÉ AGREGACE

### `team_season_stats`
Sezónní průměry týmu.

### `team_home_away_stats`
Samostatné domácí a venkovní průměry.

### `team_form_stats`
Historická okna Last 3 / 5 / 10.

### `team_rolling_stats`
Aktuální snapshot season / Last 3 / 5 / 10 a ALL/HOME/AWAY.

### `team_distribution_stats`
Mean, median, standard deviation, min, P25, P75 a max pro klíčové metriky.

### `team_threshold_stats`
Historické hit-rate hodnoty sázkových hranic pro fauly, fauly soupeře, rohy a ŽK. Nejde o predikci.

## ROZHODČÍ

### `referee_match_stats`
Zápasová historie rozhodčího.

### `referee_season_stats`
Sezónní průměry.

### `referee_form_stats`
Recent Last 3 / 5 / 10.

### `referee_team_stats`
Popisná interakce rozhodčí × tým. U malého vzorku se později musí použít shrinkage/minimum sample.

## LIGA A TABULKA

### `standings_history`
Ligová tabulka po každém hracím datu.

### `league_stats`
Sezónní tempo ligy pro góly, fauly, karty a rohy.

## MODEL DATA

### `pre_match_features`
Hlavní široká tabulka pro budoucí model a backtesting. Jeden řádek = jeden tým v jednom zápase. Vstupní feature jsou počítány pouze z minulosti. Skutečný výsledek je dostupný pouze ve sloupcích `target_*`.

### `match_pre_match_context`
Jednodušší jeden řádek na zápas pro UI a rychlé analýzy.

## AKTUÁLNÍ DASHBOARD

### `current_team_dashboard`
Aktuální týmové souhrny poslední importované sezóny.

### `current_referee_dashboard`
Aktuální rozhodcovské souhrny.

## KONTROLA

### `data_quality_report`
Po každém běhu kontroluje duplicity, počty team-match řádků, chybějící rozhodčí a chybějící targety.

### `schema_meta`
Verze datové vrstvy a základní metadata.

Úplný seznam sloupců `pre_match_features` je v `FEATURE_DICTIONARY.csv`.
