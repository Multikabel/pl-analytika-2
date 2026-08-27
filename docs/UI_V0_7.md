# UI v0.7 – mobile redesign + automatic referees

## Změny

- mobilní layout bez širokého technického dashboardu,
- aktuální kolo je hlavní pohled,
- každý zápas má kompaktní blok,
- rozhodčí se načítá z cache/delegace automaticky,
- v detailu zápasu je rozhodčí dropdown, ne ruční text,
- když delegace ještě není známá, model bezpečně imputuje referee metriky,
- hlavní kandidáti jsou filtrováni na modelový fair kurz 2,00+.

## Důležité k filtru 2,00+

V této verzi ještě není připojen živý bookmaker feed.
Proto `2,00+` znamená **modelový fair kurz**, nikoli skutečný bookmaker kurz.

V další value vrstvě bude výchozí:
`bookmaker_odds >= 2.00`
a současně se bude počítat EV/edge.
