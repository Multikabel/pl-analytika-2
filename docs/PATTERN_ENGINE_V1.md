# Pattern Engine v1

Independent read-only descriptive associations, not causal effects or predictive
advantages. No integration with UI, training, scoring, snapshots or settlement.
Dependencies: existing pandas and numpy only.

`scripts/pattern_engine.py:analyze_patterns(matches, team_stats)` accepts DataFrames
from `matches.csv` and `team_match_stats.csv`, returning `PatternResults` containing
`seasonal`, `stability` and `quality`. It reads/writes no files and mutates no inputs.

Team metrics: fouls committed, yellow cards, corners for. Referee metrics: totals
of both H/A rows of the same match, including corners. Exact stored identities
are retained; no fuzzy matching or initial correction occurs.

Four pattern types: team_weekday, team_daypart, referee_weekday, referee_daypart.
Every baseline is the complement of the category within the SAME season and
entity, also preserving venue for teams. Never a league or multi-season baseline.
Weekdays use English names independent of locale. HH:MM is already British local
time: early <15:00, afternoon 15:00–17:29, late >=17:30; no timezone conversion.

N counts observed valid metric values, not source rows. Missing/invalid dates or
times exclude the row from that factor's group AND complement. Missing referee
only excludes referee analysis. Invalid/missing metrics remain missing; totals
require both sides. Negative, non-finite or fractional count values are invalid.
Quality counts report these exclusions. Duplicate/ambiguous matches, orphan rows,
missing H/A pairs or conflicting team identities raise ValueError before analysis.
`sparse_identity` flags fewer than three matches in the season/entity/venue context.

Sample classes: N=0–2 insufficient, 3–4 very_small, 5–7 small, >=8 usable.
An absent/empty complement or absent group metric yields evaluable=false and a
missing effect. Relative effect is missing for zero baseline. Means/effects retain
full precision; no rounding, ranking or automated best-pattern selection is done.

Stability keys exclude season but include pattern, entity, venue, category and
metric. Only N_group>=5, N_baseline>0 and a non-missing effect qualify. Counts of
positive, negative and EXACTLY zero effects remain separate. All-positive=up,
all-negative=down, all-zero=neutral; any mixture (including zero + positive) is
mixed. No eligible seasons=insufficient, with missing consistency. Consistency is
max(positive, negative, neutral)/eligible, a descriptive proportion, not confidence
or probability. Raw means are never pooled or averaged across seasons.

Current/incomplete seasons remain separate season rows and obey the same N gates.
Even N>=8 is only a sample label, not evidence of significance. Baseline N is always
exposed and can be small. Repeated searches create multiple-testing risk.

The preparation, season-local effects and sign-only stability functions are
separate extension points for future confidence intervals, shrinkage,
multiple-testing correction and out-of-sample validation. Those are not part of v1.

## v2: reliability and historical walk-forward validation

`analyze_patterns_v2(matches, team_stats)` is an additional read-only API. The v1
entry point, its result columns, raw effects, sample classes, season-local
complements and stability summary are preserved. V2 returns `PatternResultsV2`:
the same `seasonal`, `stability`, `quality` plus `walk_forward` and `oos_summary`.
Seasonal results add uncertainty and shrinkage metadata, not a composite score.

### Uncertainty

With sample variances (`ddof=1`) of observed group and complement values:

```
effect_se = sqrt(s_group^2 / N_group + s_baseline^2 / N_baseline)
ci_low   = effect - 1.96 * effect_se
ci_high  = effect + 1.96 * effect_se
```

Conservative missing-value policy: either N<2 => `insufficient_n`; either variance
zero => `zero_variance`; non-finite/missing variance or effect =>
`invalid_variance_or_effect`. All three uncertainty numbers are missing in these
cases. Otherwise `uncertainty_status=available`. Constant observations are not
treated as proof of a perfectly known effect. No rounding occurs internally.
This is an approximate normal interval, not a small-sample t interval or a
cluster/serial-correlation adjustment. Football observations need not be
independent. The nominal 95% interval is not guaranteed calibrated coverage.

### Fixed shrinkage

```
effective_n = N_group * N_baseline / (N_group + N_baseline)
reliability_weight = effective_n / (effective_n + 5)
shrunk_effect = effect * reliability_weight
```

The prior strength 5 is fixed, not learned, and never optimized on OOS outcomes.
Effective N accounts for both samples: with equally sized groups of 5, weight is
1/3; with 15 each it is 0.6. It increases monotonically with either sample size,
stays in [0,1], preserves the sign, and cannot enlarge absolute effect. Zero raw
effect stays zero. Missing effect or an empty side makes all three fields missing.
Shrinkage can exist when CI cannot; the fields answer different questions. Neither
weight nor shrunk effect changes v1 raw effect or the signs used for validation.

### Walk-forward chronology and statuses

Validate each observed season-pattern against strictly earlier eligible seasons
of the SAME pattern key. Parse the start year numerically from YYYY-YY, YYYY/YYYY
or YYYY-YYYY (also YYYY/YY); require consecutive endpoints. Reject invalid labels
and duplicate/aliased season-patterns. Gaps between available seasons are allowed.
No group row is fabricated for an unobserved category/season.

Eligibility remains N_group>=5, N_baseline>0, finite raw effect. Historical
expectation requires at least two such earlier seasons. All prior effects >0
gives up; all <0 gives down; any zero or mixed signs gives mixed. There is no
majority vote. Historical seasons used are explicitly listed. Target and later
effects never enter this calculation; global v1 stability is not an input.

Status precedence:

1. Fewer than two eligible historical seasons => `not_testable`, no expectation.
2. Otherwise ineligible target => `pending`, with historical expectation retained.
3. Eligible target but historical mixed => `mixed`, no directional prediction.
4. Directional expectation and eligible target => `hit`, `miss`, or `neutral`
   for an exactly zero target effect.

This handles a partially played current season deterministically without a wall
clock. Pending does not imply that a completed sparse historical season will
eventually become eligible. A target baseline with just one observation qualifies
under the requested rule; its small N remains visible and its CI is missing.

OOS summaries count ONLY up/down predictions with hit/miss/neutral results:
`oos_tests = hits + misses + neutral`; `oos_hit_rate = hits / oos_tests`. Neutral is
in the denominator and separately visible, never mislabeled as miss. No tests
means missing hit rate. The explicit count distinguishes 1/1 from 10/10. Mixed,
pending and not_testable are excluded. Full per-season validation history is
returned separately from the aggregate. No cross-season mean is computed.

### Interpretation limits

These remain descriptive associations, not causal estimates or betting signals.
Separate sample sizes, v1 directional consistency, CI, shrunk effects and OOS
history must not be collapsed into a magical reliability score. With thousands
of overlapping patterns, false discoveries remain likely: OOS validation limits
but does NOT remove multiple-testing risk. No automatic multiple-testing
correction, significance-winner ranking or pattern selection is implemented.
Aggregate hit rate is only a descriptive diagnostic across dependent tests.
