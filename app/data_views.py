"""Read-only analytical transformations; no model or persistence imports."""
import pandas as pd

SHORT_NAMES = {
    "Manchester United": "Man Utd", "Manchester City": "Man City",
    "Nottingham Forest": "Nott'm Forest", "Crystal Palace": "C. Palace",
    "Brighton & Hove Albion": "Brighton", "Newcastle United": "Newcastle",
}
TEAM_COLUMNS = {
    "F+": "fouls_committed", "F-": "fouls_suffered",
    "ŽK+": "yellow_cards", "ŽK-": "yellow_cards_opponent",
    "R+": "corners_for", "R-": "corners_against",
}
REF_COLUMNS = {
    "F D": "home_fouls", "F H": "away_fouls", "F Σ": "total_fouls",
    "ŽK D": "home_yellow", "ŽK H": "away_yellow", "ŽK Σ": "total_yellow",
}
DETAIL_COLUMNS = ["F D", "F H", "ŽK D", "ŽK H"]


def short_team_name(name):
    return SHORT_NAMES.get(name, name)


def _numbers(frame, columns):
    result = frame.copy()
    for column in columns:
        values = pd.to_numeric(result[column], errors="coerce")
        result[column] = values.where(values.ge(0) & values.lt(float("inf")))
    return result


def latest_standings(standings, season):
    rows = standings[standings.season.astype(str).eq(str(season))].copy()
    rows["as_of_date"] = pd.to_datetime(rows.as_of_date, errors="coerce")
    rows = rows[rows.as_of_date.eq(rows.as_of_date.max())].copy()
    if rows.empty:
        raise ValueError("Pro aktuální sezonu chybí pořadí týmů.")
    rows["position"] = pd.to_numeric(rows.position, errors="coerce")
    if (rows.team.isna().any() or rows.team.duplicated().any() or
            rows.position.isna().any() or rows.position.duplicated().any() or
            not rows.position.gt(0).all() or not rows.position.mod(1).eq(0).all()):
        raise ValueError("Pořadí týmů obsahuje chybějící nebo nejednoznačné identity/pozice.")
    return rows.sort_values(["position", "team"], kind="stable").reset_index(drop=True)


def _team_rows(history, season):
    rows = _numbers(history[history.season.astype(str).eq(str(season))], TEAM_COLUMNS.values())
    ambiguous = rows.duplicated(["team", "opponent", "venue"], keep=False)
    rejected_ids = set(rows.loc[ambiguous, "match_id"])
    accepted = []
    for mid, pair in rows.groupby("match_id", sort=False):
        if (pd.isna(mid) or not str(mid).strip() or mid in rejected_ids or
                len(pair) != 2 or set(pair.venue) != {"H", "A"}):
            continue
        home = pair[pair.venue.eq("H")].iloc[0]
        away = pair[pair.venue.eq("A")].iloc[0]
        if (pd.isna(home.team) or pd.isna(away.team) or home.team == away.team or
                home.team != away.opponent or away.team != home.opponent or
                pd.isna(home.match_date) or home.match_date != away.match_date):
            continue
        inconsistent = False
        for own, other in [("F+", "F-"), ("ŽK+", "ŽK-"), ("R+", "R-")]:
            for left, right in [(home, away), (away, home)]:
                a, b = left[TEAM_COLUMNS[own]], right[TEAM_COLUMNS[other]]
                if pd.notna(a) and pd.notna(b) and a != b:
                    inconsistent = True
        if not inconsistent:
            accepted.extend(pair.index)
    return rows.loc[accepted].copy()


def build_cross_tab(history, standings, season, selected_team=None, venue="H"):
    if venue not in {"H", "A"}:
        raise ValueError("Split musí být H nebo A.")
    table = latest_standings(standings, season)
    if selected_team is not None and selected_team not in set(table.team):
        raise ValueError("Vybraný tým chybí v aktuálním pořadí.")
    valid = _team_rows(history.reset_index(drop=True), season)
    split = valid[valid.venue.eq(venue)]
    records = []
    for entry in table.itertuples():
        row = {"#": int(entry.position), "Tým": entry.team}
        if selected_team is None or entry.team == selected_team:
            matches = split[split.team.eq(entry.team)]
            values = matches[list(TEAM_COLUMNS.values())].mean()
        else:
            matches = split[split.team.eq(selected_team) & split.opponent.eq(entry.team)]
            values = matches.iloc[0] if len(matches) == 1 else {}
        row.update({label: values.get(column, float("nan")) for label, column in TEAM_COLUMNS.items()})
        records.append(row)
    result = pd.DataFrame(records)
    result.attrs["as_of_date"] = table.as_of_date.iloc[0]
    result.attrs["excluded_rows"] = int(history.season.astype(str).eq(str(season)).sum()) - len(valid)
    return result


def _referee_rows(history, season):
    columns = ["match_id", "match_date", "referee", "home_team", "away_team", *REF_COLUMNS.values()]
    rows = history.loc[history.season.astype(str).eq(str(season)), columns].copy()
    rows["match_date"] = pd.to_datetime(rows.match_date, errors="coerce")
    # Identical copies count once; conflicting copies are never arbitrarily chosen.
    rows = rows.drop_duplicates()
    rows = rows[~rows.match_id.duplicated(keep=False)]
    rows = rows.dropna(subset=["match_id", "match_date", "referee", "home_team", "away_team"])
    rows = rows[rows.referee.astype(str).str.strip().ne("") & rows.match_id.astype(str).str.strip().ne("")]
    return _numbers(rows, REF_COLUMNS.values()).sort_values(["match_date", "match_id"], kind="stable")


def _ref_means(rows):
    return {label: rows[column].mean() for label, column in REF_COLUMNS.items()}


def build_referee_summary(history, season):
    rows = _referee_rows(history, season)
    summary = [{"Rozhodčí": referee, "Zápasy": group.match_id.nunique(), **_ref_means(group)}
               for referee, group in rows.groupby("referee")]
    return pd.DataFrame(summary, columns=["Rozhodčí", "Zápasy", *REF_COLUMNS]).sort_values(
        ["Zápasy", "Rozhodčí"], ascending=[False, True], kind="stable").reset_index(drop=True)


def build_referee_detail(history, season, referee):
    rows = _referee_rows(history, season)
    rows = rows[rows.referee.eq(referee)].copy()
    form = rows.tail(5)
    match_word = "zápas" if len(form) == 1 else ("zápasy" if 2 <= len(form) <= 4 else "zápasů")
    summary = pd.DataFrame([
        {"Období": "Sezona", "Zápasy": len(rows), **_ref_means(rows)},
        {"Období": f"Forma · {len(form)} {match_word}", "Zápasy": len(form), **_ref_means(form)},
    ])
    detail = rows[["match_date", "home_team", "away_team", *[REF_COLUMNS[c] for c in DETAIL_COLUMNS]]].rename(
        columns={"match_date": "Datum", "home_team": "Domácí", "away_team": "Hosté",
                 **{REF_COLUMNS[c]: c for c in DETAIL_COLUMNS}}).reset_index(drop=True)
    return summary, detail


def referee_cell_styles(detail, season_means):
    styles = pd.DataFrame("", index=detail.index, columns=detail.columns)
    for column in DETAIL_COLUMNS:
        mean = season_means[column]
        if pd.isna(mean):
            continue
        styles.loc[detail[column].gt(mean), column] = "background-color: #e5f2e8"
        styles.loc[detail[column].lt(mean), column] = "background-color: #f7e6e6"
    return styles


def cross_tab_styles(table, selected_team):
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    styles.loc[table["Tým"].eq(selected_team), :] = "background-color: #e8edf5"
    return styles


def cross_tab_display(table, selected_team):
    """Build display-only text; Arrow nulls bypass Styler's na_rep in Streamlit."""
    averages = table.index if selected_team is None else table.index[table["Tým"].eq(selected_team)]
    display = table.copy()
    display["Tým"] = display["Tým"].map(short_team_name)
    for column in TEAM_COLUMNS:
        display[column] = [
            "—" if pd.isna(value) else format(value, ".1f" if index in averages else ".0f")
            for index, value in table[column].items()
        ]
    styles = cross_tab_styles(table, selected_team)
    return display.style.apply(lambda _: styles, axis=None)
