# UI v0.4 – Hrací kolo

Nové:
- hromadné skórování celého hracího kola,
- CSV vstup zápasů,
- filtr podle trhu,
- filtr minimální pravděpodobnosti,
- tabulka nejvyšších modelových pravděpodobností,
- export kompletního scoringu do CSV,
- zachovaný pohled jednoho zápasu a týmových statistik.

Fixtures CSV:
```csv
home_team,away_team,match_date,season,referee
Arsenal,Coventry,2026-08-21,2026-27,
```

Další plánovaná vrstva:
- bookmaker odds input,
- value = model probability × odds − 1,
- screening podle minimálního edge/value.
