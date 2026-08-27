
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
TABLES = BASE / "data" / "tables"
DB = BASE / "data" / "pl_analytika.sqlite"
SCHEMA = BASE / "database" / "schema.sql"
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
    # Historical/statistical pipeline uses completed matches only. If football-data
    # publishes future fixtures in the same CSV, blank-result rows are ignored so
    # they cannot contaminate averages or rolling windows.
    if "FTHG" in df.columns and "FTAG" in df.columns:
        df = df[df["FTHG"].notna() & df["FTAG"].notna()].copy()
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
    rebuild_extended_fast(con)
    rebuild_final_data_layer(con)
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



def rebuild_extended_fast(con):
    for table in ("team_rolling_stats","team_distribution_stats",
                  "team_threshold_stats","referee_team_stats","pre_match_features_basic"):
        con.execute(f"DELETE FROM {table}")

    t = pd.read_sql_query(
        "SELECT * FROM team_match_stats ORDER BY season,team,match_date,match_id", con
    )
    numcols = [
        "fouls_committed","fouls_suffered","corners_for","corners_against",
        "yellow_cards","yellow_cards_opponent","shots_for","shots_against",
        "shots_on_target_for","shots_on_target_against","goals_for","goals_against",
        "xg_for","xg_against"
    ]
    for c in numcols + ["red_cards"]:
        t[c] = pd.to_numeric(t[c], errors="coerce")

    # Latest descriptive snapshot for app tables.
    rolling_rows, dist_rows, threshold_rows = [], [], []
    threshold_lines = {
        "fouls_committed":[8.5,9.5,10.5,11.5,12.5,13.5,14.5,15.5],
        "fouls_suffered":[8.5,9.5,10.5,11.5,12.5,13.5,14.5,15.5],
        "corners_for":[2.5,3.5,4.5,5.5,6.5,7.5],
        "corners_against":[2.5,3.5,4.5,5.5,6.5,7.5],
        "yellow_cards":[0.5,1.5,2.5,3.5,4.5],
    }

    for (season,team), g in t.groupby(["season","team"], sort=False):
        asof = g["match_date"].max()
        for scope, sg in (
            ("ALL",g), ("HOME",g[g.venue=="H"]), ("AWAY",g[g.venue=="A"])
        ):
            if sg.empty: continue
            for window in (0,3,5,10):
                x = sg if window == 0 else sg.tail(window)
                rolling_rows.append([
                    season,asof,team,scope,window,len(x),
                    *[(float(x[c].mean()) if x[c].notna().any() else None) for c in numcols]
                ])
            for metric in numcols:
                s = sg[metric].dropna()
                if s.empty: continue
                dist_rows.append([
                    season,asof,team,scope,metric,len(s),float(s.mean()),float(s.median()),
                    float(s.std(ddof=1)) if len(s)>1 else 0.0,float(s.min()),
                    float(s.quantile(.25)),float(s.quantile(.75)),float(s.max())
                ])
            for metric, lines in threshold_lines.items():
                s=sg[metric].dropna()
                if s.empty: continue
                for line in lines:
                    hits=int((s>line).sum())
                    threshold_rows.append([
                        season,asof,team,scope,metric,line,len(s),hits,hits/len(s)
                    ])

    con.executemany("INSERT INTO team_rolling_stats VALUES ("+",".join(["?"]*20)+")", rolling_rows)
    con.executemany("INSERT INTO team_distribution_stats VALUES ("+",".join(["?"]*13)+")", dist_rows)
    con.executemany("INSERT INTO team_threshold_stats VALUES ("+",".join(["?"]*9)+")", threshold_rows)

    # Referee-team descriptive table.
    rrows=[]
    for (season,ref,team),g in t[t.referee.notna()].groupby(["season","referee","team"]):
        rrows.append([
            season,ref,team,len(g),
            g.fouls_committed.mean(),g.fouls_suffered.mean(),
            g.yellow_cards.mean(),g.yellow_cards_opponent.mean(),g.red_cards.mean()
        ])
    con.executemany("INSERT INTO referee_team_stats VALUES (?,?,?,?,?,?,?,?,?)", rrows)

    # Leakage-safe historical features, vectorized with shift + rolling.
    t = t.sort_values(["season","team","match_date","match_id"]).copy()
    g = t.groupby(["season","team"], group_keys=False)

    t["season_matches_before"] = g.cumcount()
    for col in ["fouls_committed","fouls_suffered","corners_for","corners_against","yellow_cards"]:
        t[f"season_{col}_avg"] = g[col].transform(lambda s: s.shift().expanding().mean())

    gv = t.groupby(["season","team","venue"], group_keys=False)
    t["venue_matches_before"] = gv.cumcount()
    for col in ["fouls_committed","fouls_suffered","corners_for","corners_against"]:
        t[f"venue_{col}_avg"] = gv[col].transform(lambda s: s.shift().expanding().mean())

    for n in (3,5,10):
        for col in ("fouls_committed","fouls_suffered"):
            t[f"last{n}_{col}_avg"] = g[col].transform(
                lambda s, n=n: s.shift().rolling(n, min_periods=1).mean()
            )
    for col in ("corners_for","corners_against","yellow_cards"):
        t[f"last5_{col}_avg"] = g[col].transform(
            lambda s: s.shift().rolling(5, min_periods=1).mean()
        )

    cols = [
        "match_id","season","match_date","team","opponent","venue","referee",
        "season_matches_before","season_fouls_committed_avg","season_fouls_suffered_avg",
        "season_corners_for_avg","season_corners_against_avg","season_yellow_cards_avg",
        "venue_matches_before","venue_fouls_committed_avg","venue_fouls_suffered_avg",
        "venue_corners_for_avg","venue_corners_against_avg",
        "last3_fouls_committed_avg","last5_fouls_committed_avg","last10_fouls_committed_avg",
        "last3_fouls_suffered_avg","last5_fouls_suffered_avg","last10_fouls_suffered_avg",
        "last5_corners_for_avg","last5_corners_against_avg","last5_yellow_cards_avg",
        "fouls_committed","fouls_suffered","corners_for","yellow_cards"
    ]
    rows = t[cols].where(pd.notna(t[cols]), None).values.tolist()
    con.executemany("INSERT INTO pre_match_features_basic VALUES ("+",".join(["?"]*31)+")", rows)





def rebuild_final_data_layer(con):
    """Build the final descriptive and leakage-safe pre-match tables.

    All model feature columns are computed with shift/previous dates only.
    Targets are the realised statistics from the current match and are kept
    explicitly separated with target_ prefixes.
    """
    import numpy as np

    t = pd.read_sql_query(
        "SELECT * FROM team_match_stats ORDER BY match_date, match_id, team", con
    )
    t["match_date_dt"] = pd.to_datetime(t["match_date"], errors="coerce")
    numeric = [
        "goals_for","goals_against","shots_for","shots_against",
        "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
        "corners_for","corners_against","yellow_cards","yellow_cards_opponent",
        "red_cards","red_cards_opponent","xg_for","xg_against","points"
    ]
    for c in numeric:
        t[c] = pd.to_numeric(t[c], errors="coerce")

    # ------------------------------------------------------------------
    # Team pre-match features. Current-season history only.
    # ------------------------------------------------------------------
    t = t.sort_values(["season","team","match_date_dt","match_id"]).reset_index(drop=True)
    g = t.groupby(["season","team"], sort=False, group_keys=False)
    t["matches_before"] = g.cumcount()
    t["points_before"] = g["points"].transform(lambda s: s.shift().cumsum()).fillna(0)
    t["ppg_before"] = np.where(t["matches_before"]>0, t["points_before"]/t["matches_before"], np.nan)
    t["gf_before"] = g["goals_for"].transform(lambda s: s.shift().cumsum()).fillna(0)
    t["ga_before"] = g["goals_against"].transform(lambda s: s.shift().cumsum()).fillna(0)
    t["goal_diff_before"] = t["gf_before"] - t["ga_before"]
    t["days_rest"] = g["match_date_dt"].diff().dt.days.astype(float)

    season_metrics = [
        "goals_for","goals_against","shots_for","shots_against",
        "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
        "corners_for","corners_against","yellow_cards","yellow_cards_opponent",
        "red_cards","xg_for","xg_against"
    ]
    for c in season_metrics:
        t[f"season_{c}_avg"] = g[c].transform(lambda s: s.shift().expanding().mean())

    # Venue-specific history.
    gv = t.groupby(["season","team","venue"], sort=False, group_keys=False)
    t["venue_matches_before"] = gv.cumcount()
    venue_metrics = [
        "goals_for","goals_against","shots_for","shots_against",
        "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
        "corners_for","corners_against","yellow_cards","xg_for","xg_against"
    ]
    for c in venue_metrics:
        t[f"venue_{c}_avg"] = gv[c].transform(lambda s: s.shift().expanding().mean())

    # Recent form windows. These are intentionally richer than the final model may use.
    recent_metrics = [
        "points","goals_for","goals_against","shots_for","shots_against",
        "shots_on_target_for","shots_on_target_against","fouls_committed","fouls_suffered",
        "corners_for","corners_against","yellow_cards","yellow_cards_opponent","xg_for","xg_against"
    ]
    for n in (3,5,10):
        for c in recent_metrics:
            t[f"last{n}_{c}_avg"] = g[c].transform(
                lambda s, n=n: s.shift().rolling(n, min_periods=1).mean()
            )

    # Cross-season PL recent history, useful at the start of a season. Long gaps remain visible via days_rest_pl.
    ta = t.sort_values(["team","match_date_dt","match_id"]).copy()
    ga = ta.groupby("team", sort=False, group_keys=False)
    ta["pl_matches_before"] = ga.cumcount()
    ta["days_since_last_pl_match"] = ga["match_date_dt"].diff().dt.days.astype(float)
    for c in ["fouls_committed","fouls_suffered","corners_for","corners_against","yellow_cards","points"]:
        ta[f"pl_last5_{c}_avg"] = ga[c].transform(lambda s: s.shift().rolling(5,min_periods=1).mean())
    bridge_cols = ["match_id","team","pl_matches_before","days_since_last_pl_match"] + [
        f"pl_last5_{c}_avg" for c in ["fouls_committed","fouls_suffered","corners_for","corners_against","yellow_cards","points"]
    ]
    t = t.merge(ta[bridge_cols], on=["match_id","team"], how="left")

    # ------------------------------------------------------------------
    # League table position before each calendar matchday.
    # Same-day matches all use the same pre-day snapshot.
    # ------------------------------------------------------------------
    pos_rows=[]
    for season, sg in t.groupby("season", sort=False):
        state={}
        for date, dg in sg.groupby("match_date_dt", sort=True):
            teams=set(sg["team"].unique())
            standing=[]
            for tm in teams:
                st=state.get(tm, {"p":0,"gf":0,"ga":0,"mp":0})
                standing.append((tm,st["p"],st["gf"]-st["ga"],st["gf"],st["mp"]))
            standing.sort(key=lambda x:(-x[1],-x[2],-x[3],x[0]))
            rank={tm:i+1 for i,(tm,*_) in enumerate(standing)}
            for tm in dg["team"].unique():
                st=state.get(tm,{"p":0,"gf":0,"ga":0,"mp":0})
                pos_rows.append([season,date,tm,rank.get(tm),st["p"],st["gf"]-st["ga"],st["mp"]])
            # update after the whole matchday, using team-perspective rows
            for _,r in dg.iterrows():
                st=state.setdefault(r["team"],{"p":0,"gf":0,"ga":0,"mp":0})
                if pd.notna(r["goals_for"]):
                    st["p"] += int(r["points"] if pd.notna(r["points"]) else 0)
                    st["gf"] += int(r["goals_for"])
                    st["ga"] += int(r["goals_against"])
                    st["mp"] += 1
    pos=pd.DataFrame(pos_rows,columns=["season","match_date_dt","team","position_before","table_points_before","table_gd_before","table_played_before"])
    t=t.merge(pos,on=["season","match_date_dt","team"],how="left")

    # ------------------------------------------------------------------
    # Referee features strictly before the match date.
    # ------------------------------------------------------------------
    r = pd.read_sql_query("SELECT * FROM referee_match_stats ORDER BY season,match_date,match_id",con)
    r["match_date_dt"]=pd.to_datetime(r["match_date"],errors="coerce")
    for c in ["home_fouls","away_fouls","total_fouls","home_yellow","away_yellow","total_yellow","total_red"]:
        r[c]=pd.to_numeric(r[c],errors="coerce")
    r=r.sort_values(["season","referee","match_date_dt","match_id"])
    rg=r.groupby(["season","referee"],sort=False,group_keys=False)
    r["referee_matches_before"]=rg.cumcount()
    for c in ["home_fouls","away_fouls","total_fouls","home_yellow","away_yellow","total_yellow","total_red"]:
        r[f"referee_{c}_avg_before"]=rg[c].transform(lambda s:s.shift().expanding().mean())
        if c in ["total_fouls","total_yellow"]:
            r[f"referee_last5_{c}_avg_before"]=rg[c].transform(lambda s:s.shift().rolling(5,min_periods=1).mean())
            r[f"referee_last10_{c}_avg_before"]=rg[c].transform(lambda s:s.shift().rolling(10,min_periods=1).mean())
    # Cross-season referee PL history, important in early rounds of a new season.
    ra=r.sort_values(["referee","match_date_dt","match_id"]).copy()
    rag=ra.groupby("referee",sort=False,group_keys=False)
    ra["referee_pl_matches_before"]=rag.cumcount()
    for c in ["total_fouls","total_yellow","total_red","home_fouls","away_fouls"]:
        ra[f"referee_pl_{c}_avg_before"]=rag[c].transform(lambda s:s.shift().expanding().mean())
        if c in ["total_fouls","total_yellow"]:
            ra[f"referee_pl_last10_{c}_avg_before"]=rag[c].transform(lambda s:s.shift().rolling(10,min_periods=1).mean())
    ref_cols=[c for c in r.columns if c.startswith("referee_")] + ["match_id"]
    t=t.merge(r[ref_cols],on="match_id",how="left")
    plref_cols=["match_id"]+[c for c in ra.columns if c.startswith("referee_pl_")]
    t=t.merge(ra[plref_cols],on="match_id",how="left")

    # ------------------------------------------------------------------
    # League environment before each match. Same-day fixtures share one pre-day snapshot.
    # ------------------------------------------------------------------
    m = pd.read_sql_query("""
      SELECT m.match_id,m.season,m.match_date,m.home_goals,m.away_goals,
             h.fouls_committed home_fouls,a.fouls_committed away_fouls,
             h.corners_for home_corners,a.corners_for away_corners,
             h.yellow_cards home_yellow,a.yellow_cards away_yellow
      FROM matches m
      LEFT JOIN team_match_stats h ON m.match_id=h.match_id AND h.venue='H'
      LEFT JOIN team_match_stats a ON m.match_id=a.match_id AND a.venue='A'
      ORDER BY m.season,m.match_date,m.match_id
    """,con)
    m["match_date_dt"]=pd.to_datetime(m["match_date"],errors="coerce")
    for c in ["home_goals","away_goals","home_fouls","away_fouls","home_corners","away_corners","home_yellow","away_yellow"]:
        m[c]=pd.to_numeric(m[c],errors="coerce")
    m["league_total_goals"]=m.home_goals+m.away_goals
    m["league_total_fouls"]=m.home_fouls+m.away_fouls
    m["league_total_corners"]=m.home_corners+m.away_corners
    m["league_total_yellow"]=m.home_yellow+m.away_yellow

    # Aggregate each calendar date first, then shift by date. This prevents same-day leakage.
    daily=m.groupby(["season","match_date"],as_index=False).agg(
        day_matches=("match_id","count"),
        day_goals=("league_total_goals","sum"),day_fouls=("league_total_fouls","sum"),
        day_corners=("league_total_corners","sum"),day_yellow=("league_total_yellow","sum"),
        day_home_fouls=("home_fouls","sum"),day_away_fouls=("away_fouls","sum"),
        day_home_yellow=("home_yellow","sum"),day_away_yellow=("away_yellow","sum")
    ).sort_values(["season","match_date"])
    dg=daily.groupby("season",sort=False,group_keys=False)
    daily["league_matches_before"]=dg["day_matches"].transform(lambda s:s.shift().cumsum()).fillna(0)
    cumulative_map={
        "day_goals":"league_total_goals_avg_before",
        "day_fouls":"league_total_fouls_avg_before",
        "day_corners":"league_total_corners_avg_before",
        "day_yellow":"league_total_yellow_avg_before",
        "day_home_fouls":"home_fouls_avg_before","day_away_fouls":"away_fouls_avg_before",
        "day_home_yellow":"home_yellow_avg_before","day_away_yellow":"away_yellow_avg_before"
    }
    for src,name in cumulative_map.items():
        prior_sum=dg[src].transform(lambda s:s.shift().cumsum())
        daily[name]=prior_sum/daily["league_matches_before"].replace(0,np.nan)
    league_daily_cols=["season","match_date","league_matches_before"]+list(cumulative_map.values())
    m=m.merge(daily[league_daily_cols],on=["season","match_date"],how="left")

    # Cross-season recent league tempo, also safe for the first round of a season.
    ma=m.sort_values(["match_date_dt","match_id"]).copy()
    for c in ["league_total_fouls","league_total_yellow","league_total_corners","league_total_goals"]:
        ma[f"pl_last20_{c}_avg_before"]=ma[c].shift().rolling(20,min_periods=1).mean()
    league_cols=["match_id","league_matches_before"]+list(cumulative_map.values())+[c for c in ma.columns if c.startswith("pl_last20_")]
    # Take date-safe season values from m and cross-season rolling values from ma.
    season_part=m[["match_id","league_matches_before"]+list(cumulative_map.values())]
    recent_part=ma[["match_id"]+[c for c in ma.columns if c.startswith("pl_last20_")]]
    league_feat=season_part.merge(recent_part,on="match_id",how="left")
    t=t.merge(league_feat,on="match_id",how="left")

    # ------------------------------------------------------------------
    # H2H team-perspective history across all available PL seasons.
    # ------------------------------------------------------------------
    h=t.sort_values(["team","opponent","match_date_dt","match_id"]).copy()
    hg=h.groupby(["team","opponent"],sort=False,group_keys=False)
    h["h2h_matches_before"]=hg.cumcount()
    for c in ["fouls_committed","fouls_suffered","corners_for","corners_against","yellow_cards","yellow_cards_opponent"]:
        h[f"h2h_{c}_avg_before"]=hg[c].transform(lambda s:s.shift().expanding().mean())
        h[f"h2h_last3_{c}_avg_before"]=hg[c].transform(lambda s:s.shift().rolling(3,min_periods=1).mean())
    h2h_cols=["match_id","team","h2h_matches_before"]+[c for c in h.columns if c.startswith("h2h_") and c!="h2h_matches_before"]
    t=t.merge(h[h2h_cols],on=["match_id","team"],how="left")

    # ------------------------------------------------------------------
    # Add opponent pre-match view by self-joining only non-target feature columns.
    # ------------------------------------------------------------------
    identifiers=["match_id","season","match_date","match_date_dt","team","opponent","venue","referee"]
    raw_current=set(numeric + ["result","ht_goals_for","ht_goals_against"])
    feature_cols=[c for c in t.columns if c not in identifiers and c not in raw_current and not c.startswith("target_")]
    opp=t[["match_id","team"]+feature_cols].copy()
    opp=opp.rename(columns={"team":"opponent"})
    opp=opp.rename(columns={c:f"opp_{c}" for c in feature_cols})
    t=t.merge(opp,on=["match_id","opponent"],how="left")

    # Explicit targets, never to be used as model inputs.
    targets={
        "fouls_committed":"target_fouls_committed",
        "fouls_suffered":"target_fouls_suffered",
        "corners_for":"target_corners_for",
        "corners_against":"target_corners_against",
        "yellow_cards":"target_yellow_cards",
        "yellow_cards_opponent":"target_yellow_cards_opponent",
        "shots_for":"target_shots_for",
        "shots_on_target_for":"target_shots_on_target_for",
        "goals_for":"target_goals_for",
        "xg_for":"target_xg_for"
    }
    for src,dst in targets.items():
        t[dst]=t[src]

    # Drop current-match raw stats from the final feature table except targets.
    drop_current=[c for c in numeric if c in t.columns]
    final=t.drop(columns=drop_current+["result","ht_goals_for","ht_goals_against","match_date_dt"],errors="ignore")
    # Remove duplicate merge artifacts if any.
    final=final.loc[:,~final.columns.duplicated()].copy()

    # Replace the placeholder table with the wide, reproducible feature table.
    con.execute("DROP TABLE IF EXISTS pre_match_features")
    final.to_sql("pre_match_features",con,index=False,if_exists="replace")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_prematch_match_team ON pre_match_features(match_id,team)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_prematch_team_date2 ON pre_match_features(team,match_date)")

    # ------------------------------------------------------------------
    # One-row-per-match context table, useful directly in the UI.
    # ------------------------------------------------------------------
    home=final[final.venue=="H"].copy()
    away=final[final.venue=="A"].copy()
    selected=[
        "match_id","season","match_date","team","opponent","referee","position_before","points_before","ppg_before","days_rest",
        "referee_matches_before","referee_total_fouls_avg_before","referee_total_yellow_avg_before",
        "league_matches_before","league_total_fouls_avg_before","league_total_yellow_avg_before","league_total_corners_avg_before","league_total_goals_avg_before"
    ]
    hs=home[[c for c in selected if c in home.columns]].copy()
    aw=away[[c for c in selected if c in away.columns]].copy()
    hs=hs.rename(columns={"team":"home_team","opponent":"away_team","position_before":"home_position_before","points_before":"home_points_before","ppg_before":"home_ppg_before","days_rest":"home_rest_days"})
    aw=aw[[c for c in aw.columns if c in ["match_id","position_before","points_before","ppg_before","days_rest"]]].rename(columns={"position_before":"away_position_before","points_before":"away_points_before","ppg_before":"away_ppg_before","days_rest":"away_rest_days"})
    ctx=hs.merge(aw,on="match_id",how="left")
    # standardize selected referee/league names to schema names
    ctx=ctx.rename(columns={
        "referee_total_fouls_avg_before":"referee_fouls_avg_before",
        "referee_total_yellow_avg_before":"referee_yellow_avg_before",
        "league_total_fouls_avg_before":"league_fouls_avg_before",
        "league_total_yellow_avg_before":"league_yellow_avg_before",
        "league_total_corners_avg_before":"league_corners_avg_before",
        "league_total_goals_avg_before":"league_goals_avg_before"
    })
    con.execute("DELETE FROM match_pre_match_context")
    schema_cols=[r[1] for r in con.execute("PRAGMA table_info(match_pre_match_context)")]
    for c in schema_cols:
        if c not in ctx.columns: ctx[c]=None
    ctx[schema_cols].to_sql("match_pre_match_context",con,index=False,if_exists="append")

    # ------------------------------------------------------------------
    # Current dashboard tables (latest season in the imported data).
    # ------------------------------------------------------------------
    con.execute("DELETE FROM current_team_dashboard")
    current_season=sorted(t.season.dropna().unique())[-1]
    cur=t[t.season==current_season].copy()
    latest_date=cur.match_date.max()
    # standings from existing post-match history at latest date
    st=pd.read_sql_query("SELECT * FROM standings_history WHERE season=? AND as_of_date=?",con,params=[current_season,latest_date])
    season_stats=pd.read_sql_query("SELECT * FROM team_season_stats WHERE season=?",con,params=[current_season])
    rows=[]
    for team,gx in cur.groupby("team"):
        s=season_stats[season_stats.team==team]
        ss=s.iloc[0].to_dict() if len(s) else {}
        sr=st[st.team==team]
        sd=sr.iloc[0].to_dict() if len(sr) else {}
        l5=gx.sort_values(["match_date","match_id"]).tail(5)
        rows.append([
            current_season,team,len(gx),sd.get("position"),sd.get("points"),
            (sd.get("points")/sd.get("played")) if sd.get("played") else None,
            ss.get("goals_for_avg"),ss.get("goals_against_avg"),ss.get("shots_for_avg"),ss.get("shots_against_avg"),
            ss.get("shots_on_target_for_avg"),ss.get("shots_on_target_against_avg"),ss.get("fouls_committed_avg"),ss.get("fouls_suffered_avg"),
            ss.get("corners_for_avg"),ss.get("corners_against_avg"),ss.get("yellow_cards_avg"),ss.get("yellow_cards_opponent_avg"),
            ss.get("xg_for_avg"),ss.get("xg_against_avg"),
            float(l5.points.mean()) if l5.points.notna().any() else None,
            float(l5.fouls_committed.mean()) if l5.fouls_committed.notna().any() else None,
            float(l5.fouls_suffered.mean()) if l5.fouls_suffered.notna().any() else None,
            float(l5.corners_for.mean()) if l5.corners_for.notna().any() else None,
            float(l5.corners_against.mean()) if l5.corners_against.notna().any() else None,
            float(l5.yellow_cards.mean()) if l5.yellow_cards.notna().any() else None
        ])
    con.executemany("INSERT INTO current_team_dashboard VALUES ("+",".join(["?"]*26)+")",rows)

    con.execute("DELETE FROM current_referee_dashboard")
    rr=r[r.season==current_season].copy()
    refrows=[]
    for ref,gx in rr.groupby("referee"):
        gx=gx.sort_values(["match_date_dt","match_id"])
        l5=gx.tail(5)
        refrows.append([
            current_season,ref,len(gx),gx.total_fouls.mean(),gx.total_yellow.mean(),gx.total_red.mean(),
            gx.home_fouls.mean(),gx.away_fouls.mean(),l5.total_fouls.mean(),l5.total_yellow.mean()
        ])
    con.executemany("INSERT INTO current_referee_dashboard VALUES (?,?,?,?,?,?,?,?,?,?)",refrows)

    # ------------------------------------------------------------------
    # Data quality and schema metadata.
    # ------------------------------------------------------------------
    con.execute("DELETE FROM data_quality_report")
    now=datetime.now().isoformat(timespec="seconds")
    checks=[]
    def add(name,value,ok,details=""):
        checks.append((name,float(value),"OK" if ok else "WARN",details,now))
    add("matches",len(m),len(m)>0)
    add("team_match_rows",len(t),len(t)==2*len(m),"Expected exactly two team rows per match")
    add("duplicate_match_ids",m.match_id.duplicated().sum(),m.match_id.duplicated().sum()==0)
    add("duplicate_prematch_team_rows",final.duplicated(["match_id","team"]).sum(),final.duplicated(["match_id","team"]).sum()==0)
    add("missing_referees",t.referee.isna().sum(),t.referee.isna().sum()==0)
    add("missing_foul_targets",final.target_fouls_committed.isna().sum(),final.target_fouls_committed.isna().sum()==0)
    add("prematch_rows",len(final),len(final)==len(t))
    con.executemany("INSERT INTO data_quality_report VALUES (?,?,?,?,?)",checks)
    con.execute("DELETE FROM schema_meta")
    con.executemany("INSERT INTO schema_meta(key,value) VALUES (?,?)",[
        ("data_layer_version","2.0"),
        ("feature_table","pre_match_features"),
        ("feature_policy","All non-target model features are computed from prior observations only"),
        ("source","football-data.co.uk E0.csv"),
        ("generated_at",now)
    ])


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--download-current",action="store_true")
    p.add_argument("--season-code",default="2627")
    p.add_argument("--output-name",default="2026-27.csv")
    args=p.parse_args()
    if args.download_current:
        download_current(args.season_code,args.output_name)
    run()
