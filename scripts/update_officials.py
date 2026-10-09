from pathlib import Path
import re
import os
import tempfile
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


# Known official PL article URLs. Discovery remains enabled for later rounds.
KNOWN_URLS={
    1:'https://www.premierleague.com/en/news/4688925/match-officials-for-matchweek-1',
    2:'https://www.premierleague.com/en/news/4690221/match-officials-for-matchweek-2',
    3:'https://www.premierleague.com/en/news/4698744/match-officials-for-matchweek-3',
    4:'https://www.premierleague.com/en/news/4711668/match-officials-for-matchweek-4',
    6:'https://www.premierleague.com/en/news/4729629/match-officials-for-matchweek-6',
}

# Verified against the official Premier League MW4 and MW6 articles.
# MW6 match-card IDs were resolved through the official PL match API.
# This is a deterministic safety net when premierleague.com renders article
# text in a way requests/BeautifulSoup cannot parse in GitHub Actions.
KNOWN_APPOINTMENTS={
    6:[
        ('Arsenal','Leeds','Paul Tierney'),
        ('Aston Villa','Brentford','Craig Pawson'),
        ('Chelsea','Bournemouth','Sam Barrott'),
        ('Ipswich','Fulham','Lewis Smith'),
        ('Sunderland','Brighton & Hove Albion','Tom Bramall'),
        ('Manchester United','Tottenham','Stuart Attwell'),
        ('Crystal Palace','Nottingham Forest','Peter Bankes'),
        ('Hull','Everton','Michael Salisbury'),
        ('Liverpool','Manchester City','Chris Kavanagh'),
        ('Coventry','Newcastle United','John Brooks'),
    ],
    4:[
        ('Bournemouth','Brentford','Jarred Gillett'),
        ('Aston Villa','Nottingham Forest','Andy Madley'),
        ('Chelsea','Hull','Farai Hallam'),
        ('Crystal Palace','Ipswich','Chris Kavanagh'),
        ('Liverpool','Fulham','Tom Bramall'),
        ('Tottenham','Everton','Darren England'),
        ('Sunderland','Arsenal','John Brooks'),
        ('Coventry','Brighton & Hove Albion','Tony Harrington'),
        ('Manchester United','Manchester City','Michael Oliver'),
        ('Leeds','Newcastle United','Michael Salisbury'),
    ],
}

TEAM_MAP={
    'Coventry City':'Coventry','Hull City':'Hull','Leeds United':'Leeds',
    'Ipswich Town':'Ipswich','Brighton and Hove Albion':'Brighton & Hove Albion',
    'Tottenham Hotspur':'Tottenham','AFC Bournemouth':'Bournemouth',
    'Manchester City':'Manchester City','Manchester United':'Manchester United',
    "Nott'm Forest":'Nottingham Forest','Nottingham Forest':'Nottingham Forest',
    'Brighton':'Brighton & Hove Albion','Brighton & Hove Albion':'Brighton & Hove Albion',
    'Newcastle':'Newcastle United','Newcastle United':'Newcastle United',
}

def canonical(x): return TEAM_MAP.get(str(x).strip(),str(x).strip())

SEASON = '2026-27'
CONTENT_API = 'https://api.premierleague.com/content/premierleague/text/en'
MATCH_API = 'https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v2/matches/'
HEADERS = {'User-Agent': 'Mozilla/5.0 PL-Analytika/2.0'}
COLUMNS = ['match_round','home_team','away_team','referee','source','synced_at']


def _get(url, **kwargs):
    response = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def _discover_url(round_no):
    """Use PL's content API, not the client-rendered search page.

    A successful, exhausted index means not found. Network/schema/pagination
    failures remain errors; they are never evidence of unpublished appointments.
    """
    seen = set()
    for page in range(20):
        payload = _get(CONTENT_API, params={
            'tagNames': 'franchise:referees', 'limit': 50, 'offset': page * 50,
            'detail': 'DETAILED',
        }).json()
        items = payload.get('content')
        if not isinstance(items, list):
            raise ValueError('PL article index missing content list')
        for item in items:
            ident = str(item['id'])
            if ident in seen:
                raise ValueError('PL article index repeated a page')
            seen.add(ident)
            if not re.fullmatch(rf'Match officials for Matchweek {int(round_no)}',
                                item.get('title','').strip(), re.I):
                continue
            # The title repeats every season. Require this season in its content.
            text = ' '.join(str(item.get(k) or '') for k in ('description','summary','body'))
            if not re.search(r'2026(?:/27|/2027|-27)', text):
                continue
            if not ident.isdigit():
                raise ValueError('Invalid PL article id')
            return f'https://www.premierleague.com/en/news/{ident}/match-officials-for-matchweek-{round_no}'
        # Do not trust pageInfo: current PL API reports numPages=0 even with rows.
        if len(items) < 50:
            return None
        # Completed pages entirely before this season cannot contain its articles.
        dates = [str(item.get('date',''))[:10] for item in items]
        if dates and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d < '2026-07-01' for d in dates):
            return None
    raise ValueError('PL article index pagination limit reached')


def _round_fixtures(round_no):
    x = pd.read_csv(FIXTURE_DIR / f'premier_league_{SEASON}.csv')
    q = x[(x['season'].astype(str) == SEASON) &
          (pd.to_numeric(x['match_round'], errors='coerce') == int(round_no))].copy()
    q['home_team'] = q['home_team'].map(canonical)
    q['away_team'] = q['away_team'].map(canonical)
    if len(q) != 10 or q.duplicated(['home_team','away_team']).any():
        raise ValueError(f'MW{round_no}: expected 10 unique fixtures')
    return q.reset_index(drop=True)


def _resolve_match(reference, round_no):
    if not str(reference).isdigit():
        raise ValueError('Invalid match reference')
    data = _get(MATCH_API + str(reference)).json()
    if (str(data.get('matchId')) != str(reference) or
        str(data.get('seasonId')) != '2026' or
        str(data.get('competitionId')) != '8' or
        str(data.get('matchWeek')) != str(round_no)):
        raise ValueError(f'Match reference {reference} has wrong identity/season/round')
    return canonical(data['homeTeam']['name']), canonical(data['awayTeam']['name'])


def _valid_referee(value):
    if str(value).strip().lower() in {
        'not appointed', 'not available', 'to be confirmed', 'unknown', 'tbc', 'tbd',
        'n appointed', 'n available', 't be confirmed',
    }:
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]* [A-Za-z][A-Za-z '-]*", str(value).strip()))


def _validated(rows, fixtures, diagnostics):
    """Reject all occurrences of ambiguous fixture keys, including identical duplicates."""
    if rows.empty:
        return pd.DataFrame(columns=COLUMNS)
    x = rows.copy()
    x['home_team'] = x['home_team'].map(canonical)
    x['away_team'] = x['away_team'].map(canonical)
    x['referee'] = x['referee'].map(canonical_referee)
    expected = set(zip(fixtures.home_team, fixtures.away_team))
    duplicated = x.duplicated(['home_team','away_team'], keep=False)
    keep = []
    for i, row in x.iterrows():
        pair = (row.home_team, row.away_team)
        valid = pair in expected and not duplicated.loc[i] and _valid_referee(row.referee)
        if not valid:
            diagnostics.append(f'Rejected ambiguous/invalid appointment: {pair}')
        keep.append(valid)
    return x.loc[keep].copy()


def _parse_article(html, round_no):
    soup = BeautifulSoup(html, 'html.parser')
    article = soup.find('article')
    title = soup.find('h1')
    if (article is None or title is None or not re.fullmatch(
            rf'Match officials for Matchweek {round_no}', title.get_text(' ',strip=True), re.I)
            or not re.search(r'2026(?:/27|/2027|-27)', article.get_text(' ',strip=True))):
        raise ValueError('Article title/season/body does not match requested round')
    diagnostics = []
    out = []
    current = None
    # Each card supplies its own verified identity. No positional zip of names.
    for node in article.select('[data-match-reference], p, h2, h3, h4'):
        if node.has_attr('data-match-reference'):
            current = None
            try:
                current = _resolve_match(node['data-match-reference'], round_no)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                diagnostics.append(f"Match {node['data-match-reference']}: {exc}")
            continue
        text = re.sub(r'\s+', ' ', node.get_text(' ', strip=True))
        heading = re.fullmatch(r'(.{2,50}?)\s+v(?:s\.?)?\s+(.{2,50}?)', text)
        if heading:
            current = (canonical(heading[1]), canonical(heading[2]))
            continue
        if node.name.startswith('h'):
            current = None
        match = re.match(r'^Referee:\s*([^.:]+?)(?:\.|\s+Assistants?:|$)', text, re.I)
        if match:
            if current is not None:
                out.append(dict(match_round=round_no, home_team=current[0], away_team=current[1],
                    referee=canonical_referee(match[1]), source='premierleague.com match identity',
                    synced_at=datetime.now().isoformat(timespec='seconds')))
            else:
                diagnostics.append('Referee paragraph has no verified match identity')
            # Keep identity until the next card/heading to detect duplicate paragraphs.
    result = _validated(pd.DataFrame(out, columns=COLUMNS), _round_fixtures(round_no), diagnostics)
    result.attrs['diagnostics'] = diagnostics
    return result


def load_cache():
    if CACHE.exists():
        x=pd.read_csv(CACHE)
        if 'referee' in x: x['referee']=x['referee'].map(canonical_referee)
        return x
    return pd.DataFrame(columns=['match_round','home_team','away_team','referee','source','synced_at'])

def _known_appointments(round_no):
    rows=KNOWN_APPOINTMENTS.get(int(round_no),[])
    if not rows:
        return pd.DataFrame()
    now=datetime.now().isoformat(timespec='seconds')
    return pd.DataFrame([
        {'match_round':int(round_no),'home_team':canonical(h),'away_team':canonical(a),
         'referee':canonical_referee(ref),'source':'Premier League verified appointments',
         'synced_at':now}
        for h,a,ref in rows
    ])

def _save_cache(cache):
    # Publish a complete CSV only after writing succeeds.
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                dir=CACHE.parent, suffix='.tmp', delete=False) as handle:
            name = handle.name
            cache.to_csv(handle, index=False)
        os.replace(name, CACHE)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _report(rows, fixtures, round_no, status, diagnostics):
    present = set(zip(rows.home_team, rows.away_team))
    missing = [(r.home_team,r.away_team) for r in fixtures.itertuples()
               if (r.home_team,r.away_team) not in present]
    report = dict(status=status, expected=len(fixtures), found=len(rows), missing=missing,
                  diagnostics=diagnostics)
    rows.attrs['officials_report'] = report
    print(f'Officials MW{round_no}: {status}; expected={len(fixtures)}, found={len(rows)}, missing={len(missing)}')
    for row in rows.itertuples():
        print(f'  {row.home_team} - {row.away_team}: {row.referee}')
    for home, away in missing:
        print(f'  MISSING: {home} - {away}')
    for message in diagnostics:
        print(f'  WARNING: {message}')
    return rows


def sync_officials(round_no, force=False):
    round_no = int(round_no)
    fixtures = _round_fixtures(round_no)
    cache = load_cache()
    existing_raw = cache[pd.to_numeric(cache.match_round,errors='coerce') == round_no].copy()
    diagnostics = []
    existing = _validated(existing_raw, fixtures, diagnostics)
    if len(existing) == 10 and not force:
        return _report(existing, fixtures, round_no, 'complete_cached', diagnostics)
    url = KNOWN_URLS.get(round_no)
    status = 'unpublished'
    parsed = pd.DataFrame(columns=COLUMNS)
    try:
        if not url:
            url = _discover_url(round_no)
        if url:
            status = 'published_import_failed'
            parsed = _parse_article(_get(url).text, round_no)
            diagnostics.extend(parsed.attrs.get('diagnostics', []))
        else:
            diagnostics.append('No current-season article found in the official index; publication not confirmed.')
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        status = 'published_import_failed' if url else 'discovery_failed'
        diagnostics.append(str(exc))
    # Only independently verified, fixture-validated safety nets may fill gaps.
    known = _validated(_known_appointments(round_no), fixtures, diagnostics)
    candidates = {(r.home_team,r.away_team): r for r in parsed.itertuples(index=False)}
    conflict = False
    for row in known.itertuples(index=False):
        key = (row.home_team,row.away_team)
        if key in candidates and candidates[key].referee != row.referee:
            diagnostics.append(f'Live/verified appointment conflict: {key}')
            conflict = True
        else:
            candidates.setdefault(key, row)
    merged = {(r.home_team,r.away_team): r for r in existing.itertuples(index=False)}
    # Invalid existing cache is not silently rewritten as a side-effect of partial sync.
    if len(existing_raw) != len(existing):
        diagnostics.append('Existing round cache is ambiguous; refusing cache write')
        conflict = True
    for key, row in candidates.items():
        if key in merged and merged[key].referee != row.referee:
            diagnostics.append(f'Existing/live appointment conflict: {key}; retaining cache')
            conflict = True
        else:
            merged.setdefault(key, row)
    result = pd.DataFrame([r._asdict() for r in merged.values()], columns=COLUMNS)
    if conflict:
        return _report(existing, fixtures, round_no, 'published_import_failed' if url else 'discovery_failed', diagnostics)
    if len(result) > len(existing):
        # Preserve every other round and every existing valid row verbatim in value.
        additions = result[~result.apply(lambda r: (r.home_team,r.away_team) in
                             set(zip(existing.home_team,existing.away_team)), axis=1)]
        _save_cache(pd.concat([cache, additions], ignore_index=True))
    # Cache/fallback may make the round usable, but a failed published live import
    # is still diagnosed unless the verified fallback itself covers all fixtures.
    if len(result) == 10 and (len(parsed) == 10 or len(known) == 10 or not force):
        status = 'complete'
    return _report(result, fixtures, round_no, status, diagnostics)


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

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--round', type=int)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args(argv)
    # Current round only; historical snapshots and appointments are not backfilled.
    rnd = args.round if args.round is not None else current_round_number()
    rows = sync_officials(rnd, force=args.force)
    report = rows.attrs['officials_report']
    status = report['status']
    failed = status in ('published_import_failed','discovery_failed')
    if failed:
        print(f'::error::Officials MW{rnd}: {status}; see match-level diagnostics above.')
    elif status == 'unpublished':
        print(f'::warning::Officials MW{rnd}: publication not confirmed in the official index.')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(f"\n### Officials MW{rnd}\nStatus: {status}\n\n"
                         f"Expected: {report['expected']}; found: {report['found']}; "
                         f"missing: {len(report['missing'])}\n\n")
            for row in rows.itertuples():
                handle.write(f'- {row.home_team} â€“ {row.away_team}: {row.referee}\n')
            for home, away in report['missing']:
                handle.write(f'- **MISSING: {home} â€“ {away}**\n')
            for diagnostic in report['diagnostics']:
                handle.write(f'- Diagnostic: {diagnostic}\n')
    return 1 if status in ('published_import_failed','discovery_failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
