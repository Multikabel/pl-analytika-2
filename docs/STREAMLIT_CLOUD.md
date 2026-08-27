# Streamlit Community Cloud deployment

Tato větev/balík je připravený pro nasazení na Streamlit Community Cloud.

## Deploy

1. Nahraj obsah tohoto balíku do GitHub repozitáře.
2. Otevři `https://share.streamlit.io`.
3. Přihlas se přes GitHub.
4. Klikni **Create app**.
5. Vyber repository `Multikabel/pl-analytika-2`.
6. Branch: `main`.
7. Main file path: `streamlit_app.py`.
8. V Advanced settings doporučuju Python **3.12**.
9. Klikni **Deploy**.

Po deployi dostaneš veřejnou adresu `*.streamlit.app`, kterou otevřeš normálně z mobilu.

## Proč jsou v cloud balíku i tabulky a modely

Streamlit Community Cloud při deployi klonuje GitHub repository. Lokální soubory na tvém PC
nevidí. Proto cloudová verze obsahuje v GitHubu:

- `data/tables/*.csv`
- `data/fixtures/*.csv`
- `models/*.joblib`

RAW CSV a SQLite databáze v repu nejsou potřeba.

## Aktualizace dat

Cloudový filesystem není vhodný jako trvalý zdroj dat. Doporučený workflow:

1. na PC spusť `update_and_train.bat`,
2. commitni/pushni změněné `data/tables`, `data/fixtures` a `models`,
3. Streamlit Community Cloud změny z GitHubu automaticky nasadí.

Později lze aktualizaci plně automatizovat přes GitHub Actions.
