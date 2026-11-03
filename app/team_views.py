"""Read-only team perspectives on the existing validated match dataset."""
import pandas as pd

if __package__:
    from .referee_views import METRICS, count, match_statistics, summarize, render_history
    from .data_views import short_team_name
else:
    from referee_views import METRICS, count, match_statistics, summarize, render_history
    from data_views import short_team_name

PERSPECTIVES = ['PRO', 'PROTI', 'CELKEM']
ENVIRONMENTS = {'Vše': None, 'Doma': 'H', 'Venku': 'A'}
STAT_COLUMNS = [f'{metric} {perspective}' for metric in METRICS for perspective in PERSPECTIVES]


def team_observations(matches, teams):
    valid = match_statistics(matches, teams)
    columns = ['match_id', 'season', 'Datum', 'Čas', '_time', 'Tým', 'Soupeř', 'venue', 'Prostředí', 'Výsledek', *STAT_COLUMNS]
    if valid.empty:
        return pd.DataFrame(columns=columns)
    # match_statistics already excluded conflicting identities and incomplete pairs.
    source = teams.drop_duplicates().set_index(['match_id', 'venue']).sort_index()
    rows = []
    for _, match in valid.iterrows():
        home = source.loc[(match.match_id, 'H')]
        away = source.loc[(match.match_id, 'A')]
        for venue, own, opponent in [('H', home, away), ('A', away, home)]:
            score = match['Výsledek'] if venue == 'H' else ':'.join(reversed(match['Výsledek'].split(':')))
            row = {'match_id': match.match_id, 'season': match.season, 'Datum': match.Datum,
                   'Čas': match['Čas'], '_time': match['_time'], 'Tým': own.team,
                   'Soupeř': opponent.team, 'venue': venue, 'Prostředí': 'Doma' if venue == 'H' else 'Venku',
                   'Výsledek': score}
            for metric, field in METRICS.items():
                pro, against = count(own.get(field)), count(opponent.get(field))
                row.update({f'{metric} PRO': pro, f'{metric} PROTI': against, f'{metric} CELKEM': pro + against})
            rows.append(row)
    return pd.DataFrame(rows, columns=columns).sort_values(['Datum', '_time', 'match_id', 'venue'], na_position='last').reset_index(drop=True)


def filtered(data, season, environment):
    venue = ENVIRONMENTS[environment]
    result = data[data.season == season]
    return result[result.venue == venue].copy() if venue else result.copy()


def league_reference(data, season, metric, perspective, environment):
    if perspective not in PERSPECTIVES:
        raise ValueError('Neznámý pohled statistiky.')
    rows = filtered(data, season, environment)
    if perspective == 'CELKEM':
        rows = rows.drop_duplicates('match_id')
    return summarize(rows[f'{metric} {perspective}'])


def team_ranking(data, season, metric, perspective, environment):
    rows = [{'Tým': team, 'Zápasy': len(g), **summarize(g[f'{metric} {perspective}'])}
            for team, g in filtered(data, season, environment).groupby('Tým')]
    if not rows:
        return pd.DataFrame(columns=['Pořadí', 'Tým', 'Zápasy', 'Platné N', 'Součet', 'Průměr', 'Minimum', 'Maximum'])
    table = pd.DataFrame(rows).sort_values(['Průměr', 'Tým'], ascending=[False, True], na_position='last').reset_index(drop=True)
    table.insert(0, 'Pořadí', table['Průměr'].rank(method='min', ascending=False))
    return table


def team_detail(data, season, team, perspective, environment):
    selected = filtered(data, season, environment)
    selected = selected[selected['Tým'] == team].sort_values(['Datum', '_time', 'match_id'], na_position='last')
    summary, comparison = [], []
    for metric in METRICS:
        stats = summarize(selected[f'{metric} {perspective}'])
        league = league_reference(data, season, metric, perspective, environment)
        summary.append({'Statistika': metric, 'Zápasy': len(selected), **stats})
        comparison.append({'Statistika': metric, 'Tým': stats['Průměr'], 'Liga': league['Průměr'],
                           'Rozdíl': stats['Průměr'] - league['Průměr'],
                           'N týmu': stats['Platné N'], 'N ligy': league['Platné N']})
    return pd.DataFrame(summary), pd.DataFrame(comparison), selected


def team_chart_context(history, perspective):
    """Add actual home/away context; retain 5A's team-oriented score unchanged."""
    data = history.copy()
    home = data.venue.eq('H')
    data['Domácí'] = data['Tým'].where(home, data['Soupeř'])
    data['Hosté'] = data['Soupeř'].where(home, data['Tým'])
    data['Výsledek'] = [score if venue == 'H' else ':'.join(reversed(score.split(':')))
                        for score, venue in zip(data['Výsledek'], data.venue)]
    data['Pohled'] = perspective
    return data


def render_teams(st, matches, teams):
    seasons = sorted(matches.season.dropna().astype(str).unique(), reverse=True)
    if not seasons:
        st.info('Nejsou dostupné sezony.'); return
    season = st.selectbox('Sezona', seasons, key='team_stats_season')
    metric = st.segmented_control('Statistika', list(METRICS), default='Fauly', key='team_stats_metric') or 'Fauly'
    perspective = st.segmented_control('Pohled', PERSPECTIVES, default='PRO', key='team_stats_perspective') or 'PRO'
    environment = st.segmented_control('Prostředí', list(ENVIRONMENTS), default='Vše', key='team_stats_environment') or 'Vše'
    data = team_observations(matches[matches.season == season], teams[teams.season == season])
    st.caption('PRO = tým · PROTI = soupeř · CELKEM = oba týmy. Platné N uvádí skutečný počet dostupných hodnot. Chybějící údaj není nula.')
    st.caption('Popis odehraných utkání vybrané sezony, nikoli předzápasové faktory pro historický backtest.')
    table = team_ranking(data, season, metric, perspective, environment)
    if table.empty:
        st.info('Pro zvolené filtry nejsou dostupná platná odehraná utkání.'); return
    config = {'Průměr': st.column_config.NumberColumn(format='%.1f', width=75),
              **{c: st.column_config.NumberColumn(format='%d', width=70) for c in ['Pořadí', 'Zápasy', 'Platné N', 'Součet', 'Minimum', 'Maximum']}}
    st.dataframe(table, hide_index=True, use_container_width=True, column_config=config)
    team = st.selectbox('Detail týmu', table['Tým'].tolist(), key=f'team_stats_detail_{season}_{environment}')
    summary, comparison, history = team_detail(data, season, team, perspective, environment)
    st.caption(f'{team} · {season} · {environment} · {perspective} · {len(history)} utkání')
    st.dataframe(summary, hide_index=True, use_container_width=True, column_config=config)
    st.caption('Liga: každé utkání jednou.' if perspective == 'CELKEM' else 'Liga: platná týmová pozorování odpovídající prostředí a pohledu.')
    st.dataframe(comparison, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format='+%.1f' if c == 'Rozdíl' else '%.1f') for c in ['Tým', 'Liga', 'Rozdíl']})
    render_history(st, team_chart_context(history, perspective), metric, short_team_name,
                   value_column=f'{metric} {perspective}')
    # Selected metric first; all nine perspectives remain available by horizontal scrolling.
    stats = [f'{metric} {p}' for p in PERSPECTIVES] + [c for c in STAT_COLUMNS if not c.startswith(metric+' ')]
    display = history[['Datum', 'Soupeř', 'Prostředí', 'Výsledek', *stats]]
    st.caption('Výsledek je uveden z pohledu vybraného týmu. Utkání jsou od nejstaršího.')
    st.dataframe(display, hide_index=True, use_container_width=True,
                 column_config={'Datum': st.column_config.DateColumn(format='DD.MM.YYYY', width=100),
                                **{c: st.column_config.NumberColumn(format='%d', width=85) for c in stats}})
