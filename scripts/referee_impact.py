from pathlib import Path
import re
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
TABLES=BASE/'data'/'tables'


def canonical_referee(name):
    """Convert PL long names to football-data style, e.g. Tom Bramall -> T Bramall."""
    if name is None or pd.isna(name):
        return ''
    s=re.sub(r'\s*\(pictured\)\s*','',str(name),flags=re.I).strip()
    s=re.sub(r'\s+',' ',s)
    if not s:
        return ''
    parts=s.split(' ')
    if len(parts)==1:
        return s
    first=parts[0].replace('.','')
    # Already abbreviated, e.g. "T Bramall".
    if len(first)==1:
        return f"{first.upper()} {' '.join(parts[1:])}"
    return f"{first[0].upper()} {' '.join(parts[1:])}"


def _season_key(s):
    try:
        return int(str(s).split('-')[0])
    except Exception:
        return -1


def calculate_referee_impacts(ref_matches=None, league=None, latest_season=None):
    """
    Referee / league coefficients by season, then 50/30/20 weighted over
    current, previous and two-seasons-back. Display impact is converted to
    concrete counts using the latest season league average.
    """
    if ref_matches is None:
        p=TABLES/'referee_match_stats.csv'
        ref_matches=pd.read_csv(p) if p.exists() else pd.DataFrame()
    if league is None:
        p=TABLES/'league_stats.csv'
        league=pd.read_csv(p) if p.exists() else pd.DataFrame()
    if ref_matches.empty or league.empty:
        return pd.DataFrame(columns=['referee','fouls_coeff','cards_coeff','fouls_impact','cards_impact','seasons_used'])

    r=ref_matches.copy()
    r['referee_key']=r['referee'].map(canonical_referee)
    for c in ['total_fouls','total_yellow']:
        r[c]=pd.to_numeric(r[c],errors='coerce')
    s=(r.groupby(['season','referee_key'],as_index=False)
        .agg(matches=('match_id','nunique'),fouls_avg=('total_fouls','mean'),cards_avg=('total_yellow','mean')))

    lg=league.copy()
    lg['fouls_avg']=pd.to_numeric(lg['fouls_avg'],errors='coerce')
    lg['yellow_avg']=pd.to_numeric(lg['yellow_avg'],errors='coerce')
    if latest_season is None:
        latest_season=sorted(lg['season'].dropna().astype(str).unique(),key=_season_key)[-1]
    start=_season_key(latest_season)
    seasons=[f'{start-i}-{str((start-i+1)%100).zfill(2)}' for i in range(3)]
    weights={seasons[0]:0.50,seasons[1]:0.30,seasons[2]:0.20}

    lm=lg.set_index(lg['season'].astype(str))
    latest_row=lg[lg['season'].astype(str)==str(latest_season)]
    if latest_row.empty:
        return pd.DataFrame()
    current_f=float(latest_row.iloc[0]['fouls_avg'])
    current_c=float(latest_row.iloc[0]['yellow_avg'])

    rows=[]
    for ref,g in s.groupby('referee_key'):
        parts=[]
        for season,w in weights.items():
            q=g[g['season'].astype(str)==season]
            if q.empty or season not in lm.index:
                continue
            lr=lm.loc[season]
            # lm.loc can be DF if duplicate rows exist; use first.
            if isinstance(lr,pd.DataFrame): lr=lr.iloc[0]
            rr=q.iloc[0]
            lf=float(lr['fouls_avg']) if pd.notna(lr['fouls_avg']) else np.nan
            lc=float(lr['yellow_avg']) if pd.notna(lr['yellow_avg']) else np.nan
            fc=float(rr['fouls_avg'])/lf if lf and pd.notna(rr['fouls_avg']) else np.nan
            cc=float(rr['cards_avg'])/lc if lc and pd.notna(rr['cards_avg']) else np.nan
            parts.append({'season':season,'weight':w,'matches':int(rr['matches']),
                          'fouls_avg':float(rr['fouls_avg']),'cards_avg':float(rr['cards_avg']),
                          'league_fouls_avg':lf,'league_cards_avg':lc,
                          'fouls_coeff':fc,'cards_coeff':cc,
                          'fouls_delta':float(rr['fouls_avg'])-lf,
                          'cards_delta':float(rr['cards_avg'])-lc})
        if not parts:
            continue
        def weighted(field):
            valid=[p for p in parts if pd.notna(p[field])]
            sw=sum(p['weight'] for p in valid)
            return sum(p[field]*p['weight'] for p in valid)/sw if sw else np.nan
        fc=weighted('fouls_coeff'); cc=weighted('cards_coeff')
        rows.append({'referee':ref,'fouls_coeff':fc,'cards_coeff':cc,
                     'fouls_impact':(fc-1)*current_f if pd.notna(fc) else np.nan,
                     'cards_impact':(cc-1)*current_c if pd.notna(cc) else np.nan,
                     'seasons_used':len(parts),'season_detail':parts})
    return pd.DataFrame(rows)


def impact_lookup(latest_season=None):
    x=calculate_referee_impacts(latest_season=latest_season)
    if x.empty: return {}
    return {r['referee']:r for _,r in x.iterrows()}


def _signed_cs(v):
    if v is None or pd.isna(v): return '—'
    return f'{float(v):+.1f}'.replace('.',',')


def referee_display(name, impacts=None):
    key=canonical_referee(name)
    if not key:
        return 'Rozhodčí zatím neurčen'
    impacts=impacts or {}
    r=impacts.get(key)
    if r is None:
        return key
    return f"{key} · Fauly {_signed_cs(r.get('fouls_impact'))} · Karty {_signed_cs(r.get('cards_impact'))}"
