"""Read-only Czech presentation of the existing matcher; no model adjustments."""
import pandas as pd

from pattern_matcher import match_patterns

LABELS = {"strong_candidate": "Silný vzorec", "supported": "Zajímavý vzorec",
          "weak": "Slabý vzorec", "mixed": "Nejasný vzorec"}
METRICS = {"fouls": "faulů", "yellow_cards": "ŽK", "corners": "rohů"}
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
    baseline = ("v jeho ostatních zápasech ve stejné sezoně" if referee else
                f"v ostatních {venue} zápasech ve stejné sezoně")
    direction = {"up": "více", "down": "méně"}.get(row["direction"])
    actor = f"U rozhodčího {subject} bývá" if referee else f"{subject} mívá"
    total = " celkem za oba týmy" if referee else ""
    if direction:
        title = f"{subject}: {direction} {metric}"
        text = f"{actor} {context} {direction} {metric}{total} než {baseline}."
    elif row["direction"] == "mixed":
        title = f"{subject}: nejasný směr ({metric})"
        text = f"U {subject} je {context} někdy více, jindy méně {metric}{total} nebo žádný rozdíl oproti počtu {baseline}."
    else:
        title = f"{subject}: bez jasného rozdílu ({metric})"
        text = (f"U {subject} {context} není patrný rozdíl v počtu {metric}{total} oproti počtu {baseline}."
                if row["direction"] == "neutral" else
                f"U {subject} zatím nelze určit, zda je {context} více nebo méně {metric}{total} než {baseline}.")
    # Describe only prior seasons; never label an eligible current season historical.
    prior = [s for s in row["season_effects"] if s["season"] < row["current_season"]
             and s["N_group"] >= 5 and s["N_baseline"] > 0 and pd.notna(s["effect"])]
    n = len(prior)
    same = sum(s["effect"] > 0 if direction == "více" else s["effect"] < 0 for s in prior)
    if direction and n:
        evidence = f"V předchozích sezonách s dostatečným vzorkem se tento směr opakoval {same}× z {n}. "
    elif row["direction"] == "mixed":
        evidence = "Směr není ve sledovaných sezonách jednotný. "
    elif n:
        evidence = "Ve sledovaných sezonách s dostatečným vzorkem vyšel stejný průměr jako v ostatních zápasech. "
    else:
        evidence = "Předchozí sezony zatím neposkytují dostatek údajů pro srovnání. "
    tests, hits = int(row["oos_tests"]), int(row["oos_hits"])
    if tests:
        evidence += f"Úspěšné historické kontroly: {hits}/{tests}."
        if row["oos_misses"]:
            evidence += f" Opačný směr: {int(row['oos_misses'])}."
        if row["oos_neutral"]:
            evidence += f" Bez rozdílu: {int(row['oos_neutral'])} (nepočítají se jako úspěch)."
    else:
        evidence += "Zatím není k dispozici vyhodnotitelná historická kontrola."
    if row["current_status"] == "pending":
        evidence += " Letošní vzorek je zatím příliš malý nebo chybí srovnatelné ostatní zápasy."
    return {"title": title, "label": LABELS[row["evidence_level"]],
            "text": text + "\n\nProč: " + evidence}


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
