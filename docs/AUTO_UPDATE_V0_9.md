# Automatické aktualizace v0.9

GitHub Actions workflow:
`.github/workflows/update.yml`

## Automatický běh

Workflow běží každý den v `22:15 UTC`.
V českém letním čase je to 00:15 následujícího dne.

GitHub Actions cron používá UTC.

## Ruční update

GitHub:
`Actions` → `Update PL Analytika` → `Run workflow`

## Co workflow provede

1. aktualizuje oficiální rozlosování,
2. stáhne aktuální football-data výsledky,
3. přepočítá datové tabulky,
4. vyhodnotí čekající archivované tipy,
5. přetrénuje modely,
6. vytvoří snapshot tipů na nejbližší neodehrané kolo,
7. commitne změněné tabulky, fixtures a prediction log zpět do `main`.

Pokud se nic nezměnilo, nevytvoří žádný commit.

## GitHub nastavení

Workflow potřebuje právo zapisovat do repository.

Repository:
`Settings` → `Actions` → `General` → `Workflow permissions`

zvol:
`Read and write permissions`

a ulož.

Pokud je `main` chráněná branch a zakazuje push z GitHub Actions,
je potřeba pravidlo upravit.

## Streamlit Cloud

Po pushi nového commitu Streamlit Community Cloud načte novou verzi
repozitáře. Modely `.joblib` nejsou commitovány; cloudový entrypoint je
v případě potřeby vytvoří z aktualizovaných `pre_match_features.csv`.
