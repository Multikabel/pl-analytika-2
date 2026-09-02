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


## UI v0.4 – celé hrací kolo

Streamlit nově umí nahrát CSV celého kola a hromadně spočítat fauly, rohy a ŽK pro všechny týmy a dostupné O/U hranice.

Šablona:
`data/fixtures/fixtures_template.csv`

CLI:
```bash
python scripts/score_round.py --fixtures data/fixtures/fixtures_template.csv
```


## Mobil / Streamlit Community Cloud

Cloudový entrypoint je `streamlit_app.py`.

Podrobný návod:
`docs/STREAMLIT_CLOUD.md`

Po nasazení na Streamlit Community Cloud lze aplikaci otevřít z telefonu přes běžnou `streamlit.app` URL.


## v0.7
Mobilní redesign, automatické delegace rozhodčích a výchozí filtr fair kurzu 2,00+. Viz `docs/UI_V0_7.md`.


## v0.8 – Statistika tipů
Přidán archiv predikcí a automatické vyhodnocení WIN/LOSS po aktualizaci výsledků. Viz `docs/TIP_STATS_V0_8.md`.


## v0.9 – automatické aktualizace
GitHub Actions denně aktualizuje výsledky, vyhodnotí tipy a uloží nová data zpět do repozitáře. Viz `docs/AUTO_UPDATE_V0_9.md`.


## v0.9.1
Opraven GitHub Actions rebuild: RAW sezónní CSV jsou součástí repa a `data/raw` se vytváří automaticky.


## v0.9.2
Opraven parser oficiálního rozlosování: poznámky s textem `X v Y` už nemohou vzniknout jako falešný zápas; rozpis musí projít kontrolou 380 = 38×10.


## v0.9.3
Rozpis se nyní skládá z live termínů + opravené 380zápasové cache, takže výpadek několika fixtures v HTML nezastaví GitHub Actions.


## v0.9.4
Automatické rozlosování převedeno z křehkého HTML parseru na validovaný JSON feed. Každý update musí projít kontrolou 380 zápasů / 38 kol / 20 týmů.


## v1.0.1
Vyčištěna historie testovacích tipů. Nová statistika začíná od nuly.


## v1.1 – skutečné kurzy a profit
Ručně vybrané tipy nyní vyžadují aktuální bookmaker kurz. Statistiky počítají průměrný kurz, zisk v jednotkách a ROI.


## v1.2 – celkové trhy
Přidány Fauly celkem, Rohy celkem a Karty celkem včetně fair kurzů, ručního bookmaker kurzu a automatického profit/ROI vyhodnocení.


## v1.3 – výběr tipů v detailu zápasu
Ze stránky Zápas lze nově ukládat libovolné dostupné hranice všech týmových i celkových trhů, včetně ručního bookmaker kurzu.


## v1.4 – persistent Tipy + Statistika predikcí
Tipy lze ukládat trvale přímo do GitHubu přes Streamlit Secrets. Přidána automatická auditní statistika bodových predikcí, HIT/MISS, MAE a bias.


## v1.5 – okamžité Statistiky
Výpočet jednoho zápasu i kola nyní okamžitě a trvale ukládá bodové predikce do Statistik. Opakovaný výpočet nevytváří duplicity.
