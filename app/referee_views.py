"""Read-only match statistics and referee views, independent of model scoring."""
import pandas as pd
import json
from itertools import groupby

METRICS = {'Fauly': 'fouls_committed', 'Žluté karty': 'yellow_cards', 'Rohy': 'corners_for'}


def count(value):
    try:
        n = float(value)
        return n if n >= 0 and n < float('inf') and n.is_integer() else float('nan')
    except (TypeError, ValueError):
        return float('nan')


def match_statistics(matches, teams):
    columns = ['match_id', 'season', 'Datum', 'Čas', '_time', 'Výsledek', 'Domácí', 'Hosté', 'Rozhodčí', *METRICS]
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
        time = str(r.get('kickoff_time', '')).strip()
        delta = pd.to_timedelta(time + ':00' if time.count(':') == 1 else time, errors='coerce')
        if pd.isna(delta) or not pd.Timedelta(0) <= delta < pd.Timedelta(days=1):
            delta = pd.NaT
        row.update({'Čas': time if pd.notna(delta) else 'Čas neurčen', '_time': delta,
                    'Výsledek': f"{int(count(r.home_goals))}:{int(count(r.away_goals))}"})
        for label, field in METRICS.items():
            row[label] = count(h.iloc[0].get(field)) + count(a.iloc[0].get(field))
        rows.append(row)
    return pd.DataFrame(rows, columns=columns).sort_values(['Datum', '_time', 'match_id'], na_position='last').reset_index(drop=True)


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
    return pd.DataFrame(summary), pd.DataFrame(comparison), selected.sort_values(['Datum', '_time', 'match_id'], na_position='last')


CATEGORIES = ['Nad průměrem', 'Pod průměrem', 'Na průměru']
COLORS = ['#57957D', '#BF7A76', '#87919C']


def match_history(history, metric):
    """Valid observations only; display rounding never enters classifications."""
    data = history.copy()
    data['Hodnota'] = data[metric].map(count)
    data = data[data.Hodnota.notna()].sort_values(['Datum', '_time', 'match_id'], na_position='last').copy()
    mean = summarize(data.Hodnota)['Průměr']
    data['Průměr'] = mean
    data['Rozdíl'] = data.Hodnota - mean
    data['Kategorie'] = data.Hodnota.map(lambda x: CATEGORIES[0] if x > mean else CATEGORIES[1] if x < mean else CATEGORIES[2])
    return data.reset_index(drop=True)


def streak_summary(categories):
    runs = [(kind, len(list(items))) for kind, items in groupby(categories)]
    result = {}
    for kind in CATEGORIES[:2]:
        lengths = [n for k, n in runs if k == kind]
        result[kind] = {'Nejdelší': max(lengths) if lengths else None,
                        'Průměrná délka': sum(lengths)/len(lengths) if lengths else None}
    result['current'] = runs[-1] if runs else None
    return result


def history_chart(data, metric, short_team_name):
    """Vega-Lite specification: first ordinal band is explicitly at the top."""
    if data.empty:
        return None
    values, labels = [], []
    team_view = 'Tým' in data.columns
    context_fields = ['Tým', 'Prostředí', 'Pohled'] if team_view else ['Rozhodčí']
    for i, r in data.iterrows():
        labels.append(f"{short_team_name(r['Soupeř'])} ({'D' if r['venue']=='H' else 'V'})" if team_view
                      else f"{short_team_name(r['Domácí'])} – {short_team_name(r['Hosté'])}")
        values.append({'order': int(i), 'Datum': r.Datum.strftime('%d.%m.%Y'), 'Čas': r['Čas'],
                       'Domácí': r['Domácí'], 'Hosté': r['Hosté'], 'Výsledek': r['Výsledek'],
                       **{k: r[k] for k in context_fields}, 'Statistika': metric,
                       **{k: float(r[k]) for k in ['Hodnota', 'Průměr', 'Rozdíl']}, 'Kategorie': r['Kategorie']})
    mean = values[0]['Průměr']
    tooltip = [{'field': k, 'type': 'nominal'} for k in ['Datum', 'Čas', 'Domácí', 'Hosté', 'Výsledek', *context_fields, 'Statistika']]
    tooltip += [{'field': k, 'type': 'quantitative', 'format': '.0f' if k == 'Hodnota' else '+.1f' if k == 'Rozdíl' else '.1f'} for k in ['Hodnota', 'Průměr', 'Rozdíl']]
    tooltip += [{'field': 'Kategorie', 'type': 'nominal'}]
    return {'$schema': 'https://vega.github.io/schema/vega-lite/v5.json',
            'height': max(100, len(values)*32),
            'autosize': {'type': 'fit-x', 'contains': 'padding'},
            'padding': {'top': 5, 'bottom': 5, 'left': 5, 'right': 5},
            'title': {'text': f'{metric} · Průměr {mean:.1f}'.replace('.', ','), 'anchor': 'start'},
            'layer': [
                {'data': {'values': values}, 'mark': {'type': 'bar', 'cornerRadiusEnd': 2},
                 'encoding': {'x': {'field': 'Hodnota', 'type': 'quantitative', 'title': metric,
                                    'scale': {'zero': True}, 'axis': {'tickMinStep': 1, 'gridOpacity': 0.12}},
                              'y': {'field': 'order', 'type': 'ordinal', 'sort': list(range(len(values))),
                                    'title': None, 'scale': {'reverse': False, 'paddingInner': 0.25},
                                    'axis': {'labelExpr': json.dumps(labels, ensure_ascii=False)+'[datum.value]',
                                             'labelLimit': 145, 'labelOverlap': False, 'ticks': False}},
                              'color': {'field': 'Kategorie', 'type': 'nominal',
                                        'scale': {'domain': CATEGORIES, 'range': COLORS}, 'legend': None},
                              'tooltip': tooltip}},
                {'data': {'values': [{'mean': mean}]},
                 'mark': {'type': 'rule', 'color': '#8593A3', 'strokeWidth': 2, 'strokeDash': [5, 3]},
                 'encoding': {'x': {'field': 'mean', 'type': 'quantitative'},
                              'tooltip': [{'field': 'mean', 'type': 'quantitative', 'title': 'Průměr', 'format': '.1f'}]}}],
            'config': {'view': {'stroke': None}}}


def render_history(st, history, metric, short_team_name, value_column=None):
    data = match_history(history, value_column or metric)
    if data.empty:
        st.info('Pro zvolenou statistiku nejsou dostupná platná pozorování.')
        return
    if data['_time'].isna().any():
        st.caption('U některých utkání chybí čas výkopu. V rámci stejného data jsou za známými časy; jejich přesné časové pořadí nelze doložit.')
    last = data.tail(5)
    mean = data['Průměr'].iloc[0]
    recent = last.Hodnota.mean()
    team_view = 'Tým' in data.columns
    reference = 'aktuální filtry' if team_view else 'sezona'
    st.caption(f'Posledních {len(last)} platných utkání · průměr {recent:.1f} · {reference} {mean:.1f} · rozdíl {recent-mean:+.1f}')
    context = ['Soupeř', 'Prostředí'] if team_view else ['Domácí', 'Hosté']
    display = last[['Datum', *context, 'Hodnota', 'Rozdíl', 'Kategorie']].copy()
    for c in (['Soupeř'] if team_view else ['Domácí', 'Hosté']):
        display[c] = display[c].map(short_team_name)
    st.dataframe(display, hide_index=True, use_container_width=True,
                 column_config={'Datum': st.column_config.DateColumn(format='DD.MM.YYYY'),
                                'Rozdíl': st.column_config.NumberColumn(format='%+.1f')})
    streaks = streak_summary(data.Kategorie)
    kind, length = streaks.pop('current')
    if kind == CATEGORIES[2]:
        st.caption('Poslední platné utkání je na průměru; žádná aktuální série nad/pod průměrem.')
    else:
        st.caption(f'Aktuální série: {kind.lower()} · počet utkání {length}')
    st.dataframe(pd.DataFrame([{'Kategorie': k,
                               'Nejdelší': str(v['Nejdelší']) if v['Nejdelší'] is not None else '—',
                               'Průměrná délka': f"{v['Průměrná délka']:.1f}" if v['Průměrná délka'] is not None else '—'}
                              for k, v in streaks.items()]), hide_index=True, use_container_width=True)
    st.caption('Chybějící délka (—) znamená, že taková série nenastala. Zelená = nad, červená = pod, šedá = na průměru. Popis historie, nikoli předpověď dalšího utkání.')
    st.vega_lite_chart(spec=history_chart(data, metric, short_team_name), theme='streamlit', use_container_width=True)


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
                 column_config={c: st.column_config.NumberColumn(format='%+.1f' if c == 'Rozdíl' else '%.1f') for c in ['Rozhodčí', 'Liga', 'Rozdíl']})
    detail_metric = st.segmented_control('Statistika detailu', list(METRICS), default='Fauly', key='ref_history_metric') or 'Fauly'
    render_history(st, history, detail_metric, short_team_name)
    display = history[['Datum', 'Domácí', 'Hosté', *METRICS]].copy()
    for c in ['Domácí', 'Hosté']:
        display[c] = display[c].map(short_team_name)
    st.dataframe(display, hide_index=True, use_container_width=True,
                 column_config={'Datum': st.column_config.DateColumn(format='DD.MM.YYYY', width=100),
                                **{c: st.column_config.NumberColumn(format='%d', width=65) for c in METRICS}})
