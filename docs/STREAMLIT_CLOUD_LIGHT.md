# Streamlit Cloud v0.6.1 LIGHT

Tato verze neukládá `.joblib` modely na GitHub.

Při prvním startu na Streamlit Community Cloud `streamlit_app.py`
zkontroluje modely. Pokud chybí, automaticky spustí:

`python scripts/train_count_models.py`

Modely se vytvoří z `data/tables/pre_match_features.csv` v runtime
Streamlit serveru.

Výhody:
- žádné velké binární modely při uploadu přes GitHub web,
- menší repository,
- modely vznikají ze stejného kódu a dat jako lokálně.

První cold start může být kvůli tréninku pomalejší.
