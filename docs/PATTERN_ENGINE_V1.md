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
