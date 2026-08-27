# Count models v0.2

První společná modelová vrstva pro týmové počty:

- fauly,
- rohy,
- žluté karty.

## Princip

Každý trh má vlastní konfiguraci a feature set. Všechny modely používají
ExtraTrees nad leakage-safe `pre_match_features`, doplněné jednoduchým
transparentním baseline modelem.

Predikce není celé číslo, ale očekávaná hodnota. Nad ní se počítají
pravděpodobnosti Over/Under a fair odds.

## Backtest

Walk-forward testovací sezóny:

- 2023/24
- 2024/25
- 2025/26

Trénink pro každou testovací sezonu používá pouze dřívější sezony.

| Trh | Finální MAE | Baseline MAE | Distribuce | prům. Brier |
|---|---:|---:|---|---:|
| Fauly | ~2.685 | ~2.715 | Poisson | ~0.182 |
| Rohy | ~2.267 | ~2.312 | Negative Binomial | ~0.193 |
| Žluté karty | ~1.086 | ~1.113 | Poisson | ~0.146 |

U rohů byla zvolena Negative Binomial distribuce kvůli výraznější
overdispersion. Odhad `alpha = 0.11` zlepšil historickou kalibraci proti
čistému Poissonu.

## Váhy ensemble

- fauly: 70 % ExtraTrees / 30 % baseline
- rohy: 80 % ExtraTrees / 20 % baseline
- ŽK: 80 % ExtraTrees / 20 % baseline

## Poznámka

Tato čísla nejsou zárukou budoucí výkonnosti. Jsou to historické
walk-forward výsledky nad dostupnými pěti sezonami.
