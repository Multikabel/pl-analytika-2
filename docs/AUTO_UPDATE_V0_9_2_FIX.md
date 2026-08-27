# v0.9.2 – fixture parser integrity fix

GitHub Actions previously parsed an article note containing the text
`Fulham v Chelsea` as if it were a real fixture, creating 381 rows.

The parser now:
- builds a whitelist of the 20 actual teams from local season data,
- accepts a fixture only when both sides are valid current PL teams,
- requires exactly 380 fixtures,
- requires exactly 38 rounds of 10 fixtures,
- rejects duplicate home-away pairings,
- never overwrites a previously valid cache with a failed/malformed scrape.

Expected workflow log:

`2026-27: 380 validated fixtures`
`Rounds: 38 x 10`
