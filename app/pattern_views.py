"""Read-only Czech presentation of the existing matcher; no model adjustments."""
import pandas as pd

from pattern_matcher import match_patterns

LABELS = {"strong_candidate": "Silný vzorec", "supported": "Zajímavý vzorec",
          "weak": "Slabý vzorec", "mixed": "Nejasný vzorec"}
METRICS = {"fouls": "faulů", "yellow_cards": "žlutých karet", "corners": "rohů"}
WEEKDAYS = dict(zip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
                    ("pondělních", "úterních", "středečních", "čtvrtečních", "pátečních", "sobotních", "nedělních")))
DAYPARTS = {"early": "časných", "afternoon": "odpoledních", "late": "pozdních"}
EMPTY_MESSAGE = "Pro tento zápas zatím nemáme dostatečně silný historický vzorec."


def prematch_context(schedule, officials, home, away, season, match_date, now):
    """Use one future scheduled fixture and its exact cached appointment only.

    officials must come from the season-specific cache. Historical reconstruction
    of appointments is unavailable, so do not present past fixtures as pre-match.
    """
    q = schedule.loc[(schedule.home_team == home) & (schedule.away_team == away)
                     & (schedule.season == season) & (schedule.match_date == str(match_date))]
    if len(q) != 1:
        return None
    r = q.iloc[0]
    time = r.kickoff_time
    if pd.isna(time) or not str(time).strip():
        return None
    kickoff = pd.Timestamp(f"{r.match_date} {time}").tz_localize("Europe/London")
    if pd.Timestamp(now).tz_convert("Europe/London") >= kickoff:
        return None
    referee = None
    if not officials.empty:
        refs = officials.loc[(officials.home_team == home) & (officials.away_team == away)
                             & (pd.to_numeric(officials.match_round, errors="coerce") == r.match_round)]
        if len(refs) == 1:
            value = refs.iloc[0].referee
            if isinstance(value, str) and value.strip():
                referee = value.strip()
    return dict(home_team=home, away_team=away, season=season,
                match_date=str(match_date), kickoff_time=str(time), referee=referee)


def pattern_card(row):
    subject, metric = row["subject"], METRICS[row["metric"]]
    referee = row["role"] == "referee"
    venue = "domácích" if row["venue"] == "H" else "venkovních"
    when = WEEKDAYS[row["weekday"]] if row["weekday"] else DAYPARTS[row["daypart"]]
    context = f"v {when} zápasech" if referee else (
        f"v {when} {venue} zápasech" if row["weekday"] else f"{'ve' if venue == 'venkovních' else 'v'} {venue} {when} zápasech")
    baseline = ("v ostatních zápasech stejného rozhodčího v téže sezoně" if referee else
                f"ve svých ostatních {venue} zápasech v téže sezoně")
    direction = {"up": "více", "down": "méně"}.get(row["direction"])
    if referee:
        comparison = f"V zápasech, které řídí {subject}, sledujeme celkový počet {metric} obou týmů. "
    else:
        comparison = f"Sledujeme počet {metric} týmu {subject}. "
    if direction:
        title = f"{subject} · {direction} {metric}"
        text = f"{context.capitalize()} vychází {direction} {metric} než {baseline}. "
    elif row["direction"] == "mixed":
        title = f"{subject} · nejasný směr ({metric})"
        text = f"{context.capitalize()} není rozdíl proti hodnotám {baseline} mezi sezonami jednotný. "
    else:
        title = f"{subject} · bez jasného rozdílu ({metric})"
        text = f"{context.capitalize()} zatím nemáme jasný rozdíl proti hodnotám {baseline}. "
    n = int(row["eligible_seasons"])
    tests, hits = int(row["oos_tests"]), int(row["oos_hits"])
    evidence = f"Počet sezon s dostatečným vzorkem: {n}. "
    if direction and n:
        evidence += "V těchto sezonách byl směr shodný. "
    evidence += (f"Historické kontroly na následující sezoně: {hits} úspěšných z {tests}."
                 if tests else "Zatím bez vyhodnotitelné historické kontroly na následující sezoně.")
    if row["current_status"] == "pending":
        evidence += " Aktuální sezona zatím nemá dostatečný vzorek pro toto srovnání."
    return {"title": title, "label": LABELS[row["evidence_level"]],
            "text": comparison + text + evidence}


def pattern_sections(patterns, referee=None):
    """Partition without reranking; defensively hide refs absent from context."""
    main, extra = [], []
    for row in patterns.to_dict("records"):
        if row["role"] == "referee" and (not referee or row["subject"] != referee):
            continue
        target = main if row["evidence_level"] in ("strong_candidate", "supported") else extra
        target.append(pattern_card(row))
    return {"main": main, "extra": extra, "empty_message": EMPTY_MESSAGE if not main else None}


def match_view(matches, stats, context):
    result = match_patterns(matches, stats, context)
    return pattern_sections(result.patterns, context.get("referee"))


def render_patterns(st, view):
    st.subheader("Vzorce")
    st.caption("Historické souvislosti, nikoli předpověď počtu nebo doporučení sázky. Modelové predikce se nemění.")
    def card(item):
        st.text(item["title"])
        st.caption(item["label"])
        st.write(item["text"])
    if view["empty_message"]:
        st.info(view["empty_message"])
    for item in view["main"]:
        card(item)
    if view["extra"]:
        with st.expander("Další vzorce"):
            for item in view["extra"]:
                card(item)
