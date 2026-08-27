# Foul model v0.1 – backtest

Main walk-forward validation: 2023-24, 2024-25, 2025-26.

- Ensemble MAE: **2.685**
- Ensemble RMSE: **3.354**
- Baseline MAE: **2.715**
- MAE improvement vs baseline: **0.030**
- Average Brier score over configured lines: **0.182**

## By season

| test_season   |   n | model       |   mae |   rmse |   bias |
|:--------------|----:|:------------|------:|-------:|-------:|
| 2023-24       | 760 | baseline    | 2.738 |  3.432 |  0.127 |
| 2023-24       | 760 | extra_trees | 2.747 |  3.449 |  0.049 |
| 2023-24       | 760 | ensemble    | 2.725 |  3.426 |  0.073 |
| 2024-25       | 760 | baseline    | 2.784 |  3.453 |  0.292 |
| 2024-25       | 760 | extra_trees | 2.749 |  3.403 |  0.104 |
| 2024-25       | 760 | ensemble    | 2.748 |  3.402 |  0.160 |
| 2025-26       | 760 | baseline    | 2.625 |  3.280 |  0.043 |
| 2025-26       | 760 | extra_trees | 2.579 |  3.235 |  0.074 |
| 2025-26       | 760 | ensemble    | 2.582 |  3.233 |  0.064 |
| 2026-27       |  20 | baseline    | 3.110 |  3.871 | -1.128 |
| 2026-27       |  20 | extra_trees | 2.448 |  3.163 | -0.970 |
| 2026-27       |  20 | ensemble    | 2.640 |  3.351 | -1.018 |

## Over-line Brier scores

|    line |         n |   brier |
|--------:|----------:|--------:|
|  8.5000 | 2280.0000 |  0.1776 |
|  9.5000 | 2280.0000 |  0.2162 |
| 10.5000 | 2280.0000 |  0.2370 |
| 11.5000 | 2280.0000 |  0.2329 |
| 12.5000 | 2280.0000 |  0.2057 |
| 13.5000 | 2280.0000 |  0.1687 |
| 14.5000 | 2280.0000 |  0.1282 |
| 15.5000 | 2280.0000 |  0.0867 |

## Calibration

| bin           |    n |   predicted |   actual |
|:--------------|-----:|------------:|---------:|
| (-0.001, 0.1] | 1788 |       0.068 |    0.060 |
| (0.1, 0.2]    | 3257 |       0.149 |    0.149 |
| (0.2, 0.3]    | 2545 |       0.249 |    0.244 |
| (0.3, 0.4]    | 2137 |       0.350 |    0.343 |
| (0.4, 0.5]    | 1919 |       0.451 |    0.445 |
| (0.5, 0.6]    | 1861 |       0.550 |    0.544 |
| (0.6, 0.7]    | 1920 |       0.649 |    0.642 |
| (0.7, 0.8]    | 1813 |       0.748 |    0.748 |
| (0.8, 0.9]    |  959 |       0.838 |    0.828 |
| (0.9, 1.0]    |   41 |       0.915 |    0.854 |

## Top feature importances

| feature                                  |   importance |
|:-----------------------------------------|-------------:|
| opp_season_fouls_suffered_avg            |       0.0618 |
| season_fouls_committed_avg               |       0.0582 |
| opp_pl_last5_fouls_suffered_avg          |       0.0561 |
| opp_last10_fouls_suffered_avg            |       0.0549 |
| h2h_fouls_committed_avg_before           |       0.0459 |
| opp_last5_fouls_suffered_avg             |       0.0453 |
| last10_fouls_committed_avg               |       0.0451 |
| pl_last5_fouls_committed_avg             |       0.0413 |
| opp_venue_fouls_suffered_avg             |       0.0410 |
| h2h_last3_fouls_committed_avg_before     |       0.0383 |
| last5_fouls_committed_avg                |       0.0379 |
| opp_last3_fouls_suffered_avg             |       0.0317 |
| last3_fouls_committed_avg                |       0.0304 |
| venue_fouls_committed_avg                |       0.0302 |
| referee_pl_total_fouls_avg_before        |       0.0269 |
| pl_last20_league_total_fouls_avg_before  |       0.0228 |
| referee_pl_last10_total_fouls_avg_before |       0.0219 |
| league_total_fouls_avg_before            |       0.0213 |
| home_fouls_avg_before                    |       0.0211 |
| away_fouls_avg_before                    |       0.0211 |

The 2026-27 sample contains only 20 team rows and is reported as provisional, not part of the headline validation average.