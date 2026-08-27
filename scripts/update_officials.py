from pathlib import Path
import re
from datetime import datetime, timedelta
import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE=Path(__file__).resolve().parent.parent
FIXTURE_DIR=BASE/"data"/"fixtures"
CACHE=FIXTURE_DIR/"match_officials_2026-27.csv"
FIXTURE_DIR.mkdir(parents=True,exist_ok=True)

KNOWN_URLS={
    1:"https://www.premierleague.com/en/news/4688925/match-officials-for-matchweek-1",
    2:"https://www.premierleague.com/en/news/4690221/match-officials-for-matchweek-2",
}

TEAM_MAP={
    "Coventry City":"Coventry","Hull City":"Hull","Leeds United":"Leeds",
    "Tottenham Hotspur":"Tottenham","AFC Bournemouth":"Bournemouth",
}

def canonical(x):
    return TEAM_MAP.get(str(x).strip(),str(x).strip())

def _discover_url(round_no):
    if round_no in KNOWN_URLS:
        return KNOWN_URLS[round_no]
    q=f"match officials for matchweek {round_no}"
    url="https://www.premierleague.com/en/search?q="+requests.utils.quote(q)
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
    r.raise_for_status()
    pat=rf'href="([^"]*/en/news/\d+/match-officials-for-matchweek-{round_no}[^"]*)"'
    m=re.search(pat,r.text,re.I)
    if not m:
        return None
    href=m.group(1)
    return href if href.startswith("http") else "https://www.premierleague.com"+href

def _parse_article(html,round_no):
    soup=BeautifulSoup(html,"html.parser")
    lines=[re.sub(r"\s+"," ",x).strip() for x in soup.get_text("\n").splitlines()]
    lines=[x for x in lines if x]
    out=[]
    current=None
    for line in lines:
        # Fixture heading in PL articles is normally "Home v Away".
        m=re.match(r"^(.{2,40}?)\s+v\s+(.{2,40}?)$",line)
        if m and not line.lower().startswith(("see ","how ")):
            current=(canonical(m.group(1)),canonical(m.group(2)))
            continue
        m=re.match(r"^Referee:\s*(.+)$",line,re.I)
        if m and current:
            out.append({
                "match_round":round_no,
                "home_team":current[0],
                "away_team":current[1],
                "referee":m.group(1).strip(),
                "source":"premierleague.com",
                "synced_at":datetime.now().isoformat(timespec="seconds")
            })
            current=None
    # Some PL renderings lose fixture headings in plain text. Caller will retain cache.
    return pd.DataFrame(out).drop_duplicates(["home_team","away_team"]) if out else pd.DataFrame()

def load_cache():
    if CACHE.exists():
        return pd.read_csv(CACHE)
    return pd.DataFrame(columns=["match_round","home_team","away_team","referee","source","synced_at"])

def sync_officials(round_no,force=False):
    cache=load_cache()
    existing=cache[cache.match_round==round_no] if len(cache) else cache
    if len(existing)>=10 and not force:
        return existing.copy()

    url=_discover_url(round_no)
    if not url:
        return existing.copy()
    try:
        r=requests.get(url,headers={"User-Agent":"Mozilla/5.0 PL-Analytika/2.0"},timeout=25)
        r.raise_for_status()
        parsed=_parse_article(r.text,round_no)
        if len(parsed)>=8:
            cache=cache[cache.match_round!=round_no]
            cache=pd.concat([cache,parsed],ignore_index=True)
            cache.to_csv(CACHE,index=False,encoding="utf-8-sig")
            return parsed
    except Exception:
        pass
    return existing.copy()

def referee_for_match(home,away,round_no=None):
    cache=load_cache()
    q=cache[(cache.home_team==home)&(cache.away_team==away)]
    if round_no is not None:
        q=q[q.match_round==round_no]
    return str(q.iloc[-1].referee) if len(q) else ""

def referee_choices(history_referees,automatic=""):
    vals=sorted({str(x) for x in history_referees if pd.notna(x) and str(x).strip()})
    if automatic and automatic not in vals:
        vals=[automatic]+vals
    return vals
