# v0.9.3 – fixture live/cache merge

The official PL article currently exposes only 376 of 380 fixtures in
plain text on GitHub Actions.

The updater no longer requires all 380 to be present in live HTML.

Instead:
1. old cache is filtered to the 20 valid season teams,
2. the former 381-row cache is repaired to the 380 real home/away pairings,
3. live scrape updates dates/times for the 376 fixtures it can see,
4. the missing fixtures remain from the repaired cache,
5. final schedule must still validate to exactly 380 fixtures and 38x10 rounds.

This separates schedule identity from fragile web-page rendering.
