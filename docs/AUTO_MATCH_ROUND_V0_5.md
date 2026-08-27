# Automatické aktuální hrací kolo v0.5

`Hrací kolo` už nevyžaduje ruční CSV.

Aplikace:
1. načte oficiální rozlosování Premier League,
2. porovná ho s odehranými zápasy v lokální databázi,
3. najde první Match Round, který ještě není celý odehraný,
4. zobrazí jeho zápasy,
5. jedním tlačítkem spočítá všechny neodehrané zápasy.

Zdroj rozlosování pro 2026/27:
Premier League – All 380 fixtures for 2026/27.

`update_fixtures.py` ukládá lokální cache do:
`data/fixtures/premier_league_2026-27.csv`

Cache se automaticky obnovuje po 12 hodinách. Tlačítko
`Aktualizovat rozlosování` v UI vynutí nový download.

Součástí balíku je i bootstrap prvních čtyř kol, takže aktuální kolo funguje
i při dočasném výpadku internetu. Po úspěšné synchronizaci se cache nahradí
kompletním rozpisem sezony.
