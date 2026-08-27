
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
RAW = BASE / "data" / "raw"
TABLES = BASE / "data" / "tables"
DB = BASE / "data" / "pl_analytika.sqlite"
SCHEMA = BASE / "schema.sql"
TABLES.mkdir(parents=True, exist_ok=True)

# Canonical names can be extended here without touching the database schema.
TEAM_MAP = {
    "Man United": "Manchester United",
    "Man City": "Manchester City",
    "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "Brighton": "Brighton & Hove Albion",
}

CORE_COLUMNS = {
    "Div","Date","Time","HomeTeam","AwayTeam","FTHG","FTAG","FTR",
    "HTHG","HTAG","HTR","Referee","HxG","AxG","HS","AS","HST","AST",
    "HF","AF","HC","AC","HY","AY","HR","AR"
}

def clean_columns(df):
    df = df.copy()
    df.columns = [str(c).replace("\ufeff","").replace("ï»¿","").strip() for c in df.columns]
    return df

def read_csv_any(path):
    last = None
    for enc in ("utf-8-sig","cp1252","latin1"):
        try:
            return clean_columns(pd.read_csv(path, encoding=enc))
        except Exception as e:
            last = e
    raise last

def canonical_team(name):
    if pd.isna(name):
        return name
    name = str(name).strip()
    return TEAM_MAP.get(name, name)

def infer_season(path):
    s = path.stem
    # Accept 22-23.csv, 2022-23.csv, 2223_E0.csv
    import re
    m = re.search(r"(20)?(\d{2})[-_]?(\d{2})", s)
    if not m:
        raise ValueError(f"Cannot infer season from filename: {path.name}")
    a, b = m.group(2), m.group(3)
    return f"20{a}-{b}"

def make_match_id(season, date, home, away):
    raw = f"{season}|{date}|{home}|{away}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

def as_num(v):
    x = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    if pd.isna(x):
        return None
    return float(x)

def safe_sum(*vals):
    nums = [as_num(v) for v in vals]
    nums = [x for x in nums if pd.notna(x)]
    return sum(nums) if nums else None

def result_and_points(gf, ga):
    if pd.isna(gf) or pd.isna(ga): return None, None
    if gf > ga: return "W", 3
    if gf < ga: return "L", 0
    return "D", 1

def normalize_source(path):
    df = read_csv_any(path)
    if "HomeTeam" not in df or "AwayTeam" not in df:
        raise ValueError(f"{path.name}: HomeTeam/AwayTeam missing")
    df = df[df["HomeTeam"].notna() & df["AwayTeam"].notna()].copy()
    df["HomeTeam"] = df["HomeTeam"].map(canonical_team)
    df["AwayTeam"] = df["AwayTeam"].map(canonical_team)
    if "Referee" in df:
        df["Referee"] = df["Referee"].astype("string").str.strip()
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")
    season = infer_season(path)
    df["_season"] = season
    df["_source_file"] = path.name
    return df

def initialize(con):
    con.executescript(SCHEMA.read_text(encoding="utf-8"))

def import_frame(con, df):
    imported_at = datetime.now().isoformat(timespec="seconds")
    odds_rows = []
    for _, r in df.iterrows():
        if pd.isna(r.get("Date")):
            continue
        season = r["_season"]
        home, away = r["HomeTeam"], r["AwayTeam"]
        mid = make_match_id(season, r["Date"], home, away)
        con.execute("""INSERT OR REPLACE INTO matches
          (match_id,league_code,season,match_date,kickoff_time,home_team,away_team,referee,
           home_goals,away_goals,home_ht_goals,away_ht_goals,full_time_result,half_time_result,
           source_file,imported_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (mid, r.get("Div","E0"), season, r["Date"], r.get("Time"), home, away, r.get("Referee"),
           as_num(r.get("FTHG")),as_num(r.get("FTAG")),as_num(r.get("HTHG")),as_num(r.get("HTAG")),
           r.get("FTR"),r.get("HTR"),r["_source_file"],imported_at))

        hg, ag = as_num(r.get("FTHG")), as_num(r.get("FTAG"))
        hr, hp = result_and_points(hg, ag)
        ar, ap = result_and_points(ag, hg)
        common = {
            "match_id":mid,"season":season,"match_date":r["Date"],"referee":r.get("Referee")
        }
        rows = [
          (mid,season,r["Date"],home,away,"H",r.get("Referee"),
           hg,ag,as_num(r.get("HTHG")),as_num(r.get("HTAG")),
           as_num(r.get("HS")),as_num(r.get("AS")),as_num(r.get("HST")),as_num(r.get("AST")),
           as_num(r.get("HF")),as_num(r.get("AF")),as_num(r.get("HC")),as_num(r.get("AC")),
           as_num(r.get("HY")),as_num(r.get("AY")),as_num(r.get("HR")),as_num(r.get("AR")),
           as_num(r.get("HxG")),as_num(r.get("AxG")),hp,hr),
          (mid,season,r["Date"],away,home,"A",r.get("Referee"),
           ag,hg,as_num(r.get("HTAG")),as_num(r.get("HTHG")),
           as_num(r.get("AS")),as_num(r.get("HS")),as_num(r.get("AST")),as_num(r.get("HST")),
           as_num(r.get("AF")),as_num(r.get("HF")),as_num(r.get("AC")),as_num(r.get("HC")),
           as_num(r.get("AY")),as_num(r.get("HY")),as_num(r.get("AR")),as_num(r.get("HR")),
           as_num(r.get("AxG")),as_num(r.get("HxG")),ap,ar)
        ]
        con.executemany("""INSERT OR REPLACE INTO team_match_stats VALUES
          (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)

        if pd.notna(r.get("Referee")):
            con.execute("""INSERT OR REPLACE INTO referee_match_stats VALUES
              (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (mid,season,r["Date"],r.get("Referee"),home,away,
               as_num(r.get("HF")),as_num(r.get("AF")),safe_sum(r.get("HF"),r.get("AF")),
               as_num(r.get("HY")),as_num(r.get("AY")),safe_sum(r.get("HY"),r.get("AY")),
               as_num(r.get("HR")),as_num(r.get("AR")),safe_sum(r.get("HR"),r.get("AR"))))

        # Preserve every other numeric pre-match/odds field in long format.
        for c in df.columns:
            if c.startswith("_") or c in CORE_COLUMNS:
                continue
            v = as_num(r.get(c))
            if pd.notna(v):
                odds_rows.append((mid,c,float(v),r["_source_file"]))

    con.executemany("""INSERT OR REPLACE INTO match_odds
        (match_id,odds_key,odds_value,source_file) VALUES (?,?,?,?)""", odds_rows)

def rebuild_entities(con):
    con.execute("DELETE FROM teams")
    teams = pd.read_sql_query("""
      SELECT team, MIN(season) first_season, MAX(season) last_season
      FROM team_match_stats GROUP BY team ORDER BY team""", con)
    max_season = teams["last_season"].max()
    for _,r in teams.iterrows():
        con.execute("INSERT INTO teams(team_name,first_season,last_season,active) VALUES (?,?,?,?)",
                    (r.team,r.first_season,r.last_season,1 if r.last_season==max_season else 0))

    con.execute("DELETE FROM referees")
    refs = pd.read_sql_query("""SELECT referee, MIN(season) first_season, MAX(season) last_season
       FROM referee_match_stats GROUP BY referee ORDER BY referee""", con)
    if len(refs):
        max_s = refs["last_season"].max()
        for _,r in refs.iterrows():
            con.execute("INSERT INTO referees(referee_name,first_season,last_season,active) VALUES (?,?,?,?)",
                        (r.referee,r.first_season,r.last_season,1 if r.last_season==max_s else 0))

    con.execute("DELETE FROM team_name_mapping")
    for src, canonical in TEAM_MAP.items():
        con.execute("INSERT INTO team_name_mapping VALUES (?,?)",(src,canonical))

def rebuild_team_aggregates(con):
    con.execute("DELETE FROM team_season_stats")
    con.execute("DELETE FROM team_home_away_stats")
    t = pd.read_sql_query("SELECT * FROM team_match_stats ORDER BY match_date, match_id", con)
    numeric_avg = [
      "goals_for","goals_against","shots_for","shots_against",
      "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
      "corners_for","corners_against","yellow_cards","yellow_cards_opponent",
      "red_cards","xg_for","xg_against"
    ]
    def emit(group_cols, table):
        for keys,g in t.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple): keys=(keys,)
            d=dict(zip(group_cols,keys))
            vals = [d[c] for c in group_cols]
            vals += [len(g),
                     int((g.result=="W").sum()),int((g.result=="D").sum()),int((g.result=="L").sum()),
                     int(g.points.fillna(0).sum())]
            vals += [float(g[c].mean()) if g[c].notna().any() else None for c in numeric_avg]
            placeholders=",".join(["?"]*len(vals))
            con.execute(f"INSERT INTO {table} VALUES ({placeholders})", vals)
    emit(["season","team"],"team_season_stats")
    emit(["season","team","venue"],"team_home_away_stats")

def rebuild_form(con):
    con.execute("DELETE FROM team_form_stats")
    con.execute("DELETE FROM referee_form_stats")
    t = pd.read_sql_query("SELECT * FROM team_match_stats ORDER BY match_date, match_id", con)
    avgcols = ["points","goals_for","goals_against","shots_for","shots_against",
      "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
      "corners_for","corners_against","yellow_cards","yellow_cards_opponent","red_cards","xg_for","xg_against"]
    for (season,team), g in t.groupby(["season","team"]):
        g=g.sort_values(["match_date","match_id"])
        for date in sorted(g.match_date.dropna().unique()):
            past=g[g.match_date<=date]
            for w in (3,5,10):
                x=past.tail(w)
                vals=[season,date,team,w,len(x)]
                vals += [float(x[c].mean()) if x[c].notna().any() else None for c in avgcols]
                con.execute("INSERT INTO team_form_stats VALUES ("+','.join(['?']*len(vals))+")",vals)

    r = pd.read_sql_query("SELECT * FROM referee_match_stats ORDER BY match_date, match_id", con)
    for (season,ref),g in r.groupby(["season","referee"]):
        for date in sorted(g.match_date.dropna().unique()):
            past=g[g.match_date<=date]
            for w in (3,5,10):
                x=past.tail(w)
                vals=(season,date,ref,w,len(x),
                      x.total_fouls.mean(),x.home_fouls.mean(),x.away_fouls.mean(),
                      x.total_yellow.mean(),x.total_red.mean())
                con.execute("INSERT INTO referee_form_stats VALUES (?,?,?,?,?,?,?,?,?,?)", vals)

def rebuild_referees(con):
    con.execute("DELETE FROM referee_season_stats")
    r=pd.read_sql_query("SELECT * FROM referee_match_stats",con)
    for (season,ref),g in r.groupby(["season","referee"]):
        con.execute("INSERT INTO referee_season_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
          (season,ref,len(g),g.total_fouls.mean(),g.home_fouls.mean(),g.away_fouls.mean(),
           g.total_yellow.mean(),g.home_yellow.mean(),g.away_yellow.mean(),g.total_red.mean()))

def rebuild_league(con):
    con.execute("DELETE FROM league_stats")
    m=pd.read_sql_query("""SELECT m.*, s.home_shots,s.away_shots,s.home_shots_on_target,s.away_shots_on_target,
      s.home_fouls,s.away_fouls,s.home_corners,s.away_corners,s.home_yellow,s.away_yellow,s.home_red,s.away_red,
      h.xg_for home_xg, a.xg_for away_xg
      FROM matches m
      LEFT JOIN team_match_stats h ON m.match_id=h.match_id AND h.venue='H'
      LEFT JOIN team_match_stats a ON m.match_id=a.match_id AND a.venue='A'
      LEFT JOIN (SELECT match_id,
        MAX(CASE WHEN venue='H' THEN shots_for END) home_shots,
        MAX(CASE WHEN venue='A' THEN shots_for END) away_shots,
        MAX(CASE WHEN venue='H' THEN shots_on_target_for END) home_shots_on_target,
        MAX(CASE WHEN venue='A' THEN shots_on_target_for END) away_shots_on_target,
        MAX(CASE WHEN venue='H' THEN fouls_committed END) home_fouls,
        MAX(CASE WHEN venue='A' THEN fouls_committed END) away_fouls,
        MAX(CASE WHEN venue='H' THEN corners_for END) home_corners,
        MAX(CASE WHEN venue='A' THEN corners_for END) away_corners,
        MAX(CASE WHEN venue='H' THEN yellow_cards END) home_yellow,
        MAX(CASE WHEN venue='A' THEN yellow_cards END) away_yellow,
        MAX(CASE WHEN venue='H' THEN red_cards END) home_red,
        MAX(CASE WHEN venue='A' THEN red_cards END) away_red
        FROM team_match_stats GROUP BY match_id) s ON m.match_id=s.match_id""", con)
    for season,g in m.groupby("season"):
        total=lambda a,b: (g[a]+g[b]).mean()
        con.execute("INSERT INTO league_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (season,len(g),total("home_goals","away_goals"),g.home_goals.mean(),g.away_goals.mean(),
           total("home_shots","away_shots"),total("home_shots_on_target","away_shots_on_target"),
           total("home_fouls","away_fouls"),g.home_fouls.mean(),g.away_fouls.mean(),
           total("home_corners","away_corners"),g.home_corners.mean(),g.away_corners.mean(),
           total("home_yellow","away_yellow"),total("home_red","away_red"),
           (g.home_xg+g.away_xg).mean() if (g.home_xg.notna() & g.away_xg.notna()).any() else None))

def rebuild_standings(con):
    con.execute("DELETE FROM standings_history")
    t=pd.read_sql_query("SELECT * FROM team_match_stats",con)
    for season,sg in t.groupby("season"):
        dates=sorted(sg.match_date.dropna().unique())
        for date in dates:
            past=sg[sg.match_date<=date]
            rows=[]
            for team,g in past.groupby("team"):
                gf=int(g.goals_for.fillna(0).sum()); ga=int(g.goals_against.fillna(0).sum())
                rows.append(dict(season=season,as_of_date=date,team=team,played=len(g),
                  wins=int((g.result=="W").sum()),draws=int((g.result=="D").sum()),
                  losses=int((g.result=="L").sum()),goals_for=gf,goals_against=ga,
                  goal_difference=gf-ga,points=int(g.points.fillna(0).sum())))
            st=pd.DataFrame(rows).sort_values(["points","goal_difference","goals_for","team"],
                                             ascending=[False,False,False,True])
            st["position"]=range(1,len(st)+1)
            for _,r in st.iterrows():
                con.execute("INSERT INTO standings_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",tuple(r))

def export_tables(con):
    names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for name in names:
        pd.read_sql_query(f"SELECT * FROM {name}",con).to_csv(TABLES/f"{name}.csv",index=False,encoding="utf-8-sig")

def run(raw_dir=RAW):
    con=sqlite3.connect(DB)
    initialize(con)
    files=sorted(Path(raw_dir).glob("*.csv"))
    if not files: raise FileNotFoundError(f"No CSV files in {raw_dir}")
    for path in files:
        try:
            df=normalize_source(path)
            import_frame(con,df)
            con.execute("""INSERT INTO update_log(run_at,source_file,rows_read,matches_after_update,status,message)
              VALUES (?,?,?,?,?,?)""",(datetime.now().isoformat(timespec="seconds"),path.name,len(df),
              con.execute("SELECT COUNT(*) FROM matches").fetchone()[0],"OK","Imported"))
        except Exception as e:
            con.execute("""INSERT INTO update_log(run_at,source_file,rows_read,matches_after_update,status,message)
              VALUES (?,?,?,?,?,?)""",(datetime.now().isoformat(timespec="seconds"),path.name,None,
              con.execute("SELECT COUNT(*) FROM matches").fetchone()[0],"ERROR",str(e)))
            con.commit()
            raise
    rebuild_entities(con)
    rebuild_team_aggregates(con)
    rebuild_form(con)
    rebuild_referees(con)
    rebuild_league(con)
    rebuild_standings(con)
    con.execute("""INSERT INTO data_sources(source_name,source_url,dataset,last_update)
      VALUES (?,?,?,?)""",("football-data.co.uk","https://www.football-data.co.uk/englandm.php",
      "Premier League E0.csv",datetime.now().isoformat(timespec="seconds")))
    con.commit()
    export_tables(con)
    print("Matches:",con.execute("SELECT COUNT(*) FROM matches").fetchone()[0])
    print("Team-match rows:",con.execute("SELECT COUNT(*) FROM team_match_stats").fetchone()[0])
    print("Database:",DB)
    con.close()

def download_current(season_code, output_name):
    url=f"https://www.football-data.co.uk/mmz4281/{season_code}/E0.csv"
    r=requests.get(url,timeout=30)
    r.raise_for_status()
    target=RAW/output_name
    target.write_bytes(r.content)
    print("Downloaded:",target)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--download-current",action="store_true")
    p.add_argument("--season-code",default="2627")
    p.add_argument("--output-name",default="2026-27.csv")
    args=p.parse_args()
    if args.download_current:
        download_current(args.season_code,args.output_name)
    run()
