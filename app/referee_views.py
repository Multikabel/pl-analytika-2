"""Read-only match statistics and referee views, independent of model scoring."""
import pandas as pd

METRICS = {'Fauly': 'fouls_committed', 'Žluté karty': 'yellow_cards', 'Rohy': 'corners_for'}


def count(value):
    try:
        n = float(value)
        return n if n >= 0 and n < float('inf') and n.is_integer() else float('nan')
    except (TypeError, ValueError):
        return float('nan')


def match_statistics(matches, teams):
    columns = ['match_id', 'season', 'Datum', 'Domácí', 'Hosté', 'Rozhodčí', *METRICS]
    if matches.empty or teams.empty:
        return pd.DataFrame(columns=columns)
    required = {'match_id', 'season', 'match_date', 'home_team', 'away_team', 'home_goals', 'away_goals'}
    if not required <= set(matches) or not {'match_id', 'team', 'opponent', 'venue', 'season'} <= set(teams):
        raise ValueError('Chybějí identifikační sloupce zápasů.')
    m = matches.drop_duplicates().copy()
    m = m[~m.match_id.duplicated(keep=False)]
    m = m[~m.duplicated(['season', 'home_team', 'away_team'], keep=False)]
    groups = {k: g.drop_duplicates() for k, g in teams.groupby('match_id')}
    rows = []
    for _, r in m.iterrows():
        date = pd.to_datetime(r.match_date, errors='coerce')
        if pd.isna(date) or pd.isna(r.match_id) or pd.isna(r.season):
            continue
        if r.get('league_code', 'E0') != 'E0' or any(pd.isna(count(r[c])) for c in ['home_goals', 'away_goals']):
            continue
        g = groups.get(r.match_id)
        if g is None or len(g) != 2:
            continue
        h = g[(g.venue == 'H') & (g.team == r.home_team) & (g.opponent == r.away_team) & (g.season == r.season)]
        a = g[(g.venue == 'A') & (g.team == r.away_team) & (g.opponent == r.home_team) & (g.season == r.season)]
        if len(h) != 1 or len(a) != 1 or r.home_team == r.away_team:
            continue
        ref = r.get('referee', '')
        row = dict(match_id=r.match_id, season=r.season, Datum=date, Domácí=r.home_team,
                   Hosté=r.away_team, Rozhodčí=str(ref).strip() if pd.notna(ref) else '')
        for label, field in METRICS.items():
            row[label] = count(h.iloc[0].get(field)) + count(a.iloc[0].get(field))
        rows.append(row)
    return pd.DataFrame(rows, columns=columns).sort_values(['Datum', 'match_id']).reset_index(drop=True)


def season_rows(data, season):
    return data[data.season == season].copy()


def summarize(values):
    x = values.map(count).dropna()
    return {'Platné N': len(x), 'Součet': x.sum() if len(x) else None,
            'Průměr': x.mean(), 'Minimum': x.min(), 'Maximum': x.max()}


def ranking(data, metric):
    rows = [{'Rozhodčí': ref, 'Zápasy': len(g), **summarize(g[metric])}
            for ref, g in data[data['Rozhodčí'] != ''].groupby('Rozhodčí')]
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values(['Průměr', 'Rozhodčí'], ascending=[False, True], na_position='last')
    result.insert(0, 'Pořadí', result['Průměr'].rank(method='min', ascending=False))
    return result.reset_index(drop=True)


def detail_tables(data, referee):
    selected = data[data['Rozhodčí'] == referee]
    summary, comparison = [], []
    for metric in METRICS:
        stats, league = summarize(selected[metric]), summarize(data[metric])
        summary.append({'Statistika': metric, 'Zápasy': len(selected), **stats})
        comparison.append({'Statistika': metric, 'Rozhodčí': stats['Průměr'], 'Liga': league['Průměr'],
                           'Rozdíl': stats['Průměr'] - league['Průměr'],
                           'N rozhodčí': stats['Platné N'], 'N liga': league['Platné N']})
    return pd.DataFrame(summary), pd.DataFrame(comparison), selected.sort_values(['Datum', 'match_id'])


def render_referees(st, matches, teams, canonical_referee, short_team_name):
    seasons = sorted(matches.season.dropna().astype(str).unique(), reverse=True)
    if not seasons:
        st.info('Nejsou dostupné sezony.'); return
    season = st.selectbox('Sezona', seasons, key='ref_stats_season')
    metric = st.segmented_control('Statistika', list(METRICS), default='Fauly') or 'Fauly'
    data = season_rows(match_statistics(matches, teams), season)
    data['Rozhodčí'] = data['Rozhodčí'].map(lambda r: canonical_referee(r) if r else '')
    st.caption('Rohy popisují utkání odpískaná rozhodčím, nikoli jeho rozhodcovský styl. Platné N je počet utkání s dostupnou statistikou; chybějící údaje nejsou nuly.')
    table = ranking(data, metric)
    if table.empty:
        st.info('Pro tuto sezonu nejsou dostupné zápasy s přiřazeným rozhodčím.'); return
    config = {'Průměr': st.column_config.NumberColumn(format='%.1f', width=75),
              **{c: st.column_config.NumberColumn(format='%d', width=70) for c in ['Pořadí', 'Zápasy', 'Platné N', 'Součet', 'Minimum', 'Maximum']}}
    st.dataframe(table, hide_index=True, use_container_width=True, column_config=config)
    ref = st.selectbox('Detail rozhodčího', table['Rozhodčí'].tolist(), key=f'ref_stats_detail_{season}')
    summary, comparison, history = detail_tables(data, ref)
    st.caption(f'{ref} · {len(history)} utkání · {season}')
    st.dataframe(summary, hide_index=True, use_container_width=True, column_config=config)
    st.dataframe(comparison, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format='+%.1f' if c == 'Rozdíl' else '%.1f') for c in ['Rozhodčí', 'Liga', 'Rozdíl']})
    display = history[['Datum', 'Domácí', 'Hosté', *METRICS]].copy()
    for c in ['Domácí', 'Hosté']:
        display[c] = display[c].map(short_team_name)
    st.dataframe(display, hide_index=True, use_container_width=True,
                 column_config={'Datum': st.column_config.DateColumn(format='DD.MM.YYYY', width=100),
                                **{c: st.column_config.NumberColumn(format='%d', width=65) for c in METRICS}})
