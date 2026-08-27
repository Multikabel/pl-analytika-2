# Statistika tipů v0.8

## Co se ukládá

Před zápasem se uloží neměnný snapshot tipu:

- datum a zápas,
- tým,
- trh,
- Over hranice,
- predikovaný počet,
- modelová pravděpodobnost,
- fair kurz,
- verze modelu.

Aktuální pravidlo výběru je stejné jako v UI:
pro každý tým a trh se uloží jedna nejpravděpodobnější Over hranice,
která má modelový fair kurz alespoň 2,00.

## Vyhodnocení

Po aktualizaci `team_match_stats.csv` se čekající tipy porovnají se
skutečným výsledkem:

- fauly → `fouls_committed`
- rohy → `corners_for`
- ŽK → `yellow_cards`

Half-line znamená vždy WIN/LOSS, bez remízy.

## Workflow

`update_and_train.bat` nyní dělá:

1. aktualizace rozlosování,
2. aktualizace výsledků,
3. vyhodnocení starých tipů,
4. trénink modelů,
5. uložení tipů na další/neodehrané aktuální kolo.

Historie je v:
`data/predictions/prediction_log.csv`

## Cloud

Streamlit Cloud filesystem není garantované trvalé úložiště.
Pro dlouhodobou historii je zdrojem pravdy CSV v GitHub repozitáři.
Při lokálním `update_and_train.bat` se soubor aktualizuje a je potřeba
ho spolu s ostatními cloudovými daty pushnout na GitHub.

Později lze celý update/push automatizovat přes GitHub Actions.
