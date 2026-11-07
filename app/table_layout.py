"""Presentation-only column labels; source columns and numeric types stay intact."""
SUMMARY_LABELS = {'Pořadí': '#', 'Zápasy': 'Z', 'Platné N': 'N', 'Součet': 'Σ',
                  'Průměr': 'Ø', 'Minimum': 'Min', 'Maximum': 'Max'}
SUMMARY_LEGEND = 'Z = odehrané zápasy, N = platná pozorování, Σ = součet, Ø = průměr, Min / Max = minimum / maximum. — = nedostupná hodnota.'


def summary_config(st):
    return {key: st.column_config.NumberColumn(label, width=38 if key in {'Pořadí', 'Zápasy', 'Platné N'} else 52,
                format='%.1f' if key == 'Průměr' else '%d', help=key)
            for key, label in SUMMARY_LABELS.items()}


def comparison_config(st, entity):
    counts = ['N týmu', 'N ligy'] if entity == 'Tým' else ['N rozhodčí', 'N liga']
    return {**{c: st.column_config.NumberColumn(c, width=70, format='%+.1f' if c == 'Rozdíl' else '%.1f')
               for c in [entity, 'Liga', 'Rozdíl']},
            **{c: st.column_config.NumberColumn(c, width=70, format='%d')
               for c in counts}}
