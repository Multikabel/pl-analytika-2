# v0.9.4 – machine-readable fixture feed

The official Premier League article remains the authoritative reference,
but its rendered HTML was not reliable enough for unattended GitHub Actions.

Automatic schedule updates now use the machine-readable JSON feed:

`https://fixturedownload.com/feed/json/epl-2026`

The pipeline validates every download before saving it:

- exactly 380 fixtures,
- exactly 38 rounds,
- exactly 10 matches per round,
- exactly 20 teams,
- no duplicate home-away pairing.

Team names are normalized to the same canonical names used by
PL Analytika.

Dates/times are converted from UTC to Europe/London before storage.

If the JSON feed is temporarily unavailable, the updater keeps a
previously validated local schedule instead of corrupting it.
