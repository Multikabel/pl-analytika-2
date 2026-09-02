# v1.5 – Statistiky se ukládají při výpočtu

Předchozí v1.4 vytvářela auditní predikce hlavně přes GitHub Actions.
To znamenalo, že ručně spočítaný jeden zápas nemusel být hned vidět
ve Statistikách.

v1.5 mění chování:

## Zápas
Kliknutí na `Spočítat zápas` automaticky archivuje:
- 3 týmové trhy domácího,
- 3 týmové trhy hostujícího,
- 3 celkové trhy zápasu.

Celkem 9 bodových predikcí.

## Kolo
Kliknutí na `Spočítat zbývající zápasy` archivuje stejné bodové predikce
pro všechny právě spočítané zápasy.

## Persistence
`model_prediction_log.csv` používá stejný GitHub persistence mechanismus
jako ručně ukládané Tipy. Streamlit Secrets token tedy stačí ten, který
je už nastavený.

## Duplicity
ID auditní predikce je určeno:
sezóna + datum + zápas + tým/celkem + trh.

Opakované spočítání stejného zápasu nevytvoří další statistický řádek.
Historická predikce se tím nepřepíše novější verzí modelu.

GitHub Actions nadále:
- vyhodnocuje odehrané predikce,
- a může automaticky vytvořit snapshot ještě nespočítaného aktuálního kola.
