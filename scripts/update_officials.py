from pathlib import Path
import re
import html as html_lib
import argparse
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup

from referee_impact import canonical_referee

BASE=Path(__file__).resolve().parent.parent
FIXTURE_DIR=BASE/'data'/'fixtures'
TABLES=BASE/'data'/'tables'
CACHE=FIXTURE_DIR/'match_officials_2026-27.csv'
FIXTURE_DIR.mkdir(parents=True,exist_ok=True)

# Known official PL article URLs. Discovery remains enabled for later rounds.
KNOWN_URLS={
    1:'https://www.premierleague.com/en/news/4688925/match-officials-for-matchweek-1',
    2:'https://www.premierleague.com/en/news/4690221/match-officials-for-matchweek-2',
    3:'https://www.premierleague.com/en/news/4698744/match-officials-for-matchweek-3',
    4:'https://www.premierleague.com/en/news/4711668/match-officials-for-matchweek-4',
}

TEAM_MAP={
    'Coventry City':'Coventry','Hull City':'Hull','Leeds United':'Leeds',
    'Tottenham Hotspur':'Tottenham','AFC Bournemouth':'Bournemouth',
    'Manchester City':'Manchester City','Manchester United':'Manchester United',
    "Nott'm Forest":'Nottingham Forest','Nottingham Forest':'Nottingham Forest',
    'Brighton':'Brighton & Hove Albion','Brighton & Hove Albion':'Brighton & Hove Albion',
    'Newcastle':'Newcastle United','Newcastle United':'Newcastle United',
}

def canonical(x): return TEAM_MAP.get(str(x).strip(),str(x).strip())

def _match_url(text,round_no):
    # English, Arabic and other locale mirrors carry the same article id/slug.
    pats=[
        rf'https?://(?:www\.)?premierleague\.com/(?:en|ar|es|th)/news/\d+/match-officials-for-matchweek-{round_no}',
        rf'/(?:en|ar|es|th)/news/\d+/match-officials-for-matchweek-{round_no}',
    ]
    for pat in pats:
        m=re.search(pat,text,re.I)
        if m:
            u=m.group(0).replace('\\/','/')
            if u.startswith('/'):
                u='https://www.premierleague.com'+u
            # Always request English rendering when possible.
            return re.sub(r'premierleague\.com/(ar|es|th)/', 'premierleague.com/en/', u, flags=re.I)
    return None

def _discover_url(round_no):
    if round_no in KNOWN_URLS:
        return KNOWN_URLS[round_no]
    headers={'User-Agent':'Mozilla/5.0 PL-Analytika/2.0'}
    q=f'match officials for matchweek {round_no}'
    # Premier League's own search page first.
    urls=[
        'https://www.premierleague.com/en/search?q='+requests.utils.quote(q),
        'https://www.premierleague.com/en/news?type=-1',
        # HTML search fallback. Failure here is harmless; cache is retained.
        'https://html.duckduckgo.com/html/?q='+requests.utils.quote(f'site:premierleague.com/en/news "{q}"'),
    ]
    for url in urls:
        try:
            r=requests.get(url,headers=headers,timeout=20)
            r.raise_for_status()
            found=_match_url(r.text,round_no)
            if found:
                return found
        except Exception:
            continue
    return None

def _round_fixtures(round_no):
    p=FIXTURE_DIR/'premier_league_2026-27.csv'
    if not p.exists(): return pd.DataFrame()
    x=pd.read_csv(p)
    q=x[pd.to_numeric(x['match_round'],errors='coerce')==int(round_no)].copy()
    if q.empty: return q
    q['home_team']=q['home_team'].map(canonical); q['away_team']=q['away_team'].map(canonical)
    # Preserve validated fixture-feed order. PL appointment articles use the same fixture order.
    return q.reset_index(drop=True)

def _parse_article(html,round_no):
    soup=BeautifulSoup(html,'html.parser')
    lines=[re.sub(r'\s+',' ',x).strip() for x in soup.get_text('\n').splitlines()]
    lines=[x for x in lines if x]
    out=[]; current=None; ordered_refs=[]
    for line in lines:
        m=re.match(r'^(.{2,50}?)\s+v\s+(.{2,50}?)$',line)
        if m and not line.lower().startswith(('see ','how ')):
            current=(canonical(m.group(1)),canonical(m.group(2)))
            continue
        m=re.match(r'^Referee:\s*([^\.]+)',line,re.I)
        if m:
            ref=canonical_referee(m.group(1).strip())
            ordered_refs.append(ref)
            if current:
                out.append({'match_round':round_no,'home_team':current[0],'away_team':current[1],
                            'referee':ref,'source':'premierleague.com','synced_at':datetime.now().isoformat(timespec='seconds')})
                current=None

    # Some PL responses keep article text inside serialized HTML/JSON rather than
    # visible DOM nodes. If BeautifulSoup found too few appointments, scan the raw
    # response as well. This keeps the official PL page as the only source.
    if len(ordered_refs)<10:
        raw=html_lib.unescape(html)
        raw=raw.replace('\\u003A', ':').replace('\\u002E', '.').replace('\\"', '"')
        raw_refs=[canonical_referee(x.strip()) for x in re.findall(r'Referee:\s*([^.<"\\]{2,80})',raw,re.I)]
        # Preserve order while removing accidental duplicates from serialized copies.
        dedup=[]
        for ref in raw_refs:
            if ref and (not dedup or ref!=dedup[-1]):
                dedup.append(ref)
        if len(dedup)>=10:
            ordered_refs=dedup[:10]

    # New PL article rendering often omits fixture headings from plain text while
    # retaining referee paragraphs in fixture order. Safely map the 10 appointments
    # onto the validated 10-match round schedule.
    if len(out)<8 and len(ordered_refs)==10:
        fx=_round_fixtures(round_no)
        if len(fx)==10:
            out=[]
            for i,r in fx.iterrows():
                out.append({'match_round':round_no,'home_team':r.home_team,'away_team':r.away_team,
                            'referee':ordered_refs[i],'source':'premierleague.com sequence + validated fixture order',
                            'synced_at':datetime.now().isoformat(timespec='seconds')})
    return pd.DataFrame(out).drop_duplicates(['home_team','away_team']) if out else pd.DataFrame()

def load_cache():
    if CACHE.exists():
        x=pd.read_csv(CACHE)
        if 'referee' in x: x['referee']=x['referee'].map(canonical_referee)
        return x
    return pd.DataFrame(columns=['match_round','home_team','away_team','referee','source','synced_at'])

def sync_officials(round_no,force=False):
    round_no=int(round_no)
    cache=load_cache()
    existing=cache[pd.to_numeric(cache.match_round,errors='coerce')==round_no] if len(cache) else cache
    if len(existing)>=10 and not force:
        return existing.copy()
    url=_discover_url(round_no)
    if not url:
        print(f'Officials MW{round_no}: article not discovered; keeping {len(existing)} cached rows.')
        return existing.copy()
    try:
        r=requests.get(url,headers={'User-Agent':'Mozilla/5.0 PL-Analytika/2.0'},timeout=25)
        r.raise_for_status()
        parsed=_parse_article(r.text,round_no)
        if len(parsed)>=8:
            cache=cache[pd.to_numeric(cache.match_round,errors='coerce')!=round_no]
            cache=pd.concat([cache,parsed],ignore_index=True)
            cache.to_csv(CACHE,index=False,encoding='utf-8-sig')
            print(f'Officials MW{round_no}: saved {len(parsed)} appointments from {url}')
            return parsed
        print(f'Officials MW{round_no}: parsed only {len(parsed)} rows; keeping cache.')
    except Exception as e:
        print(f'Officials MW{round_no}: sync failed ({e}); keeping cache.')
    return existing.copy()

def referee_for_match(home,away,round_no=None):
    cache=load_cache(); home=canonical(home); away=canonical(away)
    q=cache[(cache.home_team.map(canonical)==home)&(cache.away_team.map(canonical)==away)]
    if round_no is not None:
        q=q[pd.to_numeric(q.match_round,errors='coerce')==int(round_no)]
    return canonical_referee(q.iloc[-1].referee) if len(q) else ''

def referee_choices(history_referees,automatic=''):
    vals=sorted({canonical_referee(x) for x in history_referees if pd.notna(x) and str(x).strip()})
    if automatic and canonical_referee(automatic) not in vals:
        vals=[canonical_referee(automatic)]+vals
    return vals

def current_round_number():
    from update_fixtures import load_fixtures,current_round
    schedule=load_fixtures('2026-27',auto_sync=False)
    p=TABLES/'team_match_stats.csv'
    completed=pd.DataFrame(columns=['home_team','away_team'])
    if p.exists():
        h=pd.read_csv(p)
        s=sorted(h.season.dropna().astype(str).unique())[-1]
        completed=h[(h.season.astype(str)==s)&(h.venue=='H')][['team','opponent']].rename(columns={'team':'home_team','opponent':'away_team'})
    rnd,_=current_round(schedule,completed)
    return rnd

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--round',type=int); ap.add_argument('--force',action='store_true')
    args=ap.parse_args()
    if args.round:
        rounds=[args.round]
    else:
        current=current_round_number()
        rounds=list(range(1,current+1))
    for rnd in rounds:
        x=sync_officials(rnd,force=args.force)
        print(f'MW{rnd}: {len(x)} officials available')
