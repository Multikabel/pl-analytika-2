# v0.9.1 – GitHub Actions RAW-data fix

Oprava chyby:

`FileNotFoundError: data/raw/2026-27.csv`

## Co bylo špatně

Cloud-light repozitář neobsahoval RAW sezónní CSV a `update_data.py`
se při automatickém downloadu snažil zapisovat do neexistující `data/raw/`.

Navíc kompletní rebuild dat potřebuje historické RAW sezóny.

## Oprava

- `data/raw/2022-23.csv` až `2026-27.csv` jsou nyní součástí repozitáře,
- `update_data.py` vždy vytvoří `data/raw/`,
- GitHub Actions ověří přítomnost historických sezon před update,
- změněný aktuální `data/raw/2026-27.csv` se commitne zpět do repozitáře.

Po nahrání této verze spusť:
Actions → Update PL Analytika → Run workflow.
