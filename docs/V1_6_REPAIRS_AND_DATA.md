# v1.6

- GitHub update pipeline tolerates temporary fixture/referee/model failures and keeps last known-good current-season CSV.
- Referee appointments parser supports the new PL article rendering where fixture headings are omitted, mapping 10 referee paragraphs to the validated 10-fixture round order.
- Added known official PL URLs for MW3 and MW4 and automatic discovery fallback for later rounds.
- Referee names are normalized to football-data style so referee history/model features can match appointments.
- Model prediction audit identity no longer uses match date. Existing duplicate match/team/market rows are deduplicated. Settlement finds the actual match by fixture identity and corrects the recorded date.
- Manual single-match scoring uses the schedule date whenever the selected teams match a scheduled fixture.
- New Data page with Team/Referee selector, chronological tables, and three grouped bar charts (fouls/cards/corners).
- Referee foul/card coefficients are calculated by season against league average, weighted 50/30/20 over the latest three seasons, and displayed as concrete count impact (e.g. Fauly +2.1, Karty -0.6).
