# Pattern Engine v3: pre-match matcher

`scripts/pattern_matcher.py:match_patterns(matches, team_stats, fixture)` returns
`MatchPatterns(patterns, context, quality)`. It is a pure, read-only transformation
with no IO, UI, ML, scoring, snapshot or settlement integration. V1/v2 definitions
and results are unchanged. The module reuses their transformations rather than
accepting precomputed, potentially future-contaminated summaries.

## Availability and matching

Fixture requires exact stored home/away identities, season and YYYY-MM-DD date.
Kickoff HH:MM and referee may be missing. British local time is not converted.
No target outcome is required or consulted; extra outcome fields are ignored.
Referee must be supplied as known pre-match: never inferred from a results row.
Unknown or missing referee produces no referee patterns; no fuzzy name matching.
Missing kickoff disables only daypart matching, not weekday matching.

Before any aggregation, retain only results dated strictly before the fixture's
calendar day and from seasons no later than its season. Exclude even earlier
kickoffs on the same day and the exact target season/home/away identity regardless
of its stored date. Missing dates cannot prove availability and are excluded.
V1 validation still rejects ambiguous historical match/team rows.

Use all available prior-day history to compute existing v2 season-local effects.
Only the two relevant team/venue contexts and the exact referee are needed, but
ALL their weekday/daypart categories remain available when computing complements.
Then select the fixture weekday or daypart. All three metrics are considered;
both up and down, weak and mixed patterns are retained. No new pattern family.

Season effects carry raw/shrunk effects, N, CI and sample classes. Original v1
stability and v2 OOS histories are recomputed on this bounded history. Eligible
current-season observations may participate, but N<5 never creates a miss or
changes direction consistency. Current-season status/N is always separate.
If its category has no observed row, status is pending, N_group=0, with the
available complement N exposed. No history for a pattern means no invented row.
`historical_eligible_seasons` counts only seasons strictly before fixture season.

This is an as-of reconstruction from supplied result tables, not proof of their
original publication times or of when appointments were announced. Callers must
supply referee/context actually known at the desired pre-match time. Revised
historical stats cannot be reconstructed to old revisions without versioned data.

## Fixed evidence rules (before real-data smoke)

Apply in this order, symmetrically for up/down:

1. v1 direction=mixed => **mixed** (including a mix with exactly zero).
2. v1 direction up/down; >=3 historical eligible seasons; >=2 actual directional
   OOS tests; all tests hit, no miss/neutral => **strong_candidate**.
3. v1 direction up/down; >=2 historical eligible seasons; >=1 actual directional
   OOS test; all tests hit, no miss/neutral => **supported**.
4. Otherwise => **weak**, including all-zero/neutral direction.

These are fixed descriptive categories, not betting recommendations or a magical
numeric score. OOS 1/1 is never strong; 2/2 alone is not sufficient. No threshold
is tuned against smoke results. Multiple testing and small samples remain concerns.

## Deterministic ranking

Lexicographic, not a weighted score:

1. strong_candidate, supported, weak, mixed;
2. OOS test count descending;
3. v1 eligible season count descending (includes eligible current season);
4. v1 direction consistency descending;
5. absolute shrunk effect of the latest eligible season descending;
6. full v1 pattern KEY ascending to resolve ties deterministically.

Missing tie-break values sort last. No cross-season absolute mean is created.
The final magnitude tie-break is metric-specific in meaning and is NOT a measure
of importance comparable across fouls/corners/cards. Full results are retained.

## Smoke selection

Before evidence calculation, choose the first three upcoming MW6 fixtures ordered
by date, kickoff, home team: Arsenal–Leeds, Aston Villa–Brentford,
Chelsea–Bournemouth. Also count categories over all ten MW6 fixtures. Use only
unambiguous appointments for exact round/home/away identities in the local cache;
do not infer referees from results. No persistent analytic files are written.
