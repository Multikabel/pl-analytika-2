from pathlib import Path
from datetime import date
import subprocess
import sys
import joblib
import numpy as np
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"
MODELS = BASE / "models"
TABLES = BASE / "data" / "tables"

sys.path.insert(0, str(SCRIPTS))
from count_common import load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows

st.set_page_config(page_title="PL Analytika 2.0", page_icon="⚽", layout="wide")

MARKETS = ("fouls", "corners", "yellow_cards")
MARKET_LABEL = {"fouls":"Fauly", "corners":"Rohy", "yellow_cards":"ŽK"}

@st.cache_data(show_spinner=False)
def load_team_history():
    p = TABLES / "team_match_stats.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    return df

@st.cache_resource(show_spinner=False)
def load_models():
    out = {}
    for market in MARKETS:
        p = MODELS / f"{market}_model.joblib"
        if p.exists():
            out[market] = joblib.load(p)
    return out

def pct(x):
    return f"{100*x:.1f}%"

def odds(x):
    return f"{x:.2f}" if np.isfinite(x) else "—"

def predict_fixture(home, away, match_date, season, referee):
    fixture = build_fixture_rows(home, away, referee, str(match_date), season)
    models = load_models()
    records = []
    for market in MARKETS:
        if market not in models:
            continue
        art = models[market]
        cfg = art["config"]
        for c in cfg["features"]:
            if c not in fixture.columns:
                fixture[c] = np.nan
        pred, extra, baseline = ensemble_prediction(
            art["model"], fixture, art["train_mean"], cfg
        )
        for i, row in fixture.iterrows():
            rec = {
                "Tým": row["team"],
                "H/A": row["venue"],
                "Trh": MARKET_LABEL[market],
                "Predikce": round(float(pred[i]), 2),
                "Model": round(float(extra[i]), 2),
                "Baseline": round(float(baseline[i]), 2),
            }
            for line in cfg["over_lines"]:
                p = float(over_probability([pred[i]], line, cfg)[0])
                rec[f"O {line}"] = p
                rec[f"Fair O {line}"] = float(fair_odds([p])[0])
            records.append(rec)
    return pd.DataFrame(records)

def compact_market_table(pred, market):
    x = pred[pred["Trh"] == MARKET_LABEL[market]].copy()
    if x.empty:
        return x
    cfg = load_config(market)
    cols = ["Tým", "H/A", "Predikce"]
    for line in cfg["over_lines"]:
        cols += [f"O {line}", f"Fair O {line}"]
    x = x[cols]
    for line in cfg["over_lines"]:
        x[f"O {line}"] = x[f"O {line}"].map(pct)
        x[f"Fair O {line}"] = x[f"Fair O {line}"].map(odds)
    return x

st.title("PL Analytika 2.0")
st.caption("Tabulkový dashboard · fauly · rohy · žluté karty")

history = load_team_history()
models = load_models()

if history.empty:
    st.error("Chybí data/tables/team_match_stats.csv. Nejdřív spusť update_and_train.bat.")
    st.stop()

teams = sorted(history["team"].dropna().unique())
last_season = sorted(history["season"].dropna().unique())[-1]

with st.sidebar:
    st.subheader("Zápas")
    home = st.selectbox("Domácí", teams, index=0)
    away_options = [t for t in teams if t != home]
    away = st.selectbox("Hosté", away_options, index=min(1, len(away_options)-1))
    season = st.text_input("Sezóna", value=last_season)
    match_date = st.date_input("Datum", value=date.today())
    referee = st.text_input("Rozhodčí", value="", placeholder="volitelné")
    run = st.button("Spočítat zápas", type="primary", use_container_width=True)

    st.divider()
    if st.button("Obnovit data + modely", use_container_width=True):
        with st.spinner("Aktualizuji data a modely…"):
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS/"update_data.py"), "--download-current"],
                cwd=BASE, capture_output=True, text=True
            )
            if proc.returncode == 0:
                proc2 = subprocess.run(
                    [sys.executable, str(SCRIPTS/"train_count_models.py")],
                    cwd=BASE, capture_output=True, text=True
                )
                if proc2.returncode == 0:
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.success("Hotovo.")
                else:
                    st.error(proc2.stderr[-1200:])
            else:
                st.error(proc.stderr[-1200:])

if len(models) < 3:
    st.warning("Nejsou natrénované všechny modely. Spusť `update_and_train.bat`.")

# Default screen: current data overview, no click-maze.
latest = history[history["season"] == last_season].copy()
latest_date = latest["match_date"].max()
st.subheader("Datový přehled")
c1,c2,c3,c4 = st.columns(4)
c1.metric("Sezóna", last_season)
c2.metric("Zápasů v datech", int(len(latest)/2))
c3.metric("Poslední datum", latest_date.strftime("%d.%m.%Y") if pd.notna(latest_date) else "—")
c4.metric("Modely", f"{len(models)}/3")

if run:
    if home == away:
        st.error("Domácí a hosté musí být různé týmy.")
    else:
        with st.spinner("Počítám pre-match profil…"):
            pred = predict_fixture(home, away, match_date, season, referee)

        st.header(f"{home} – {away}")
        st.caption(f"{match_date.strftime('%d.%m.%Y')} · {referee or 'rozhodčí nezadaný'}")

        # One dense summary table first.
        summary = pred.pivot(index="Tým", columns="Trh", values="Predikce").reset_index()
        ordered = ["Tým"] + [c for c in ["Fauly","Rohy","ŽK"] if c in summary.columns]
        st.dataframe(summary[ordered], use_container_width=True, hide_index=True)

        tabs = st.tabs(["Fauly", "Rohy", "Žluté karty", "Model vs baseline"])
        with tabs[0]:
            st.dataframe(compact_market_table(pred,"fouls"), use_container_width=True, hide_index=True)
        with tabs[1]:
            st.dataframe(compact_market_table(pred,"corners"), use_container_width=True, hide_index=True)
        with tabs[2]:
            st.dataframe(compact_market_table(pred,"yellow_cards"), use_container_width=True, hide_index=True)
        with tabs[3]:
            comp = pred[["Tým","Trh","Predikce","Model","Baseline"]].copy()
            comp["Rozdíl model-baseline"] = (comp["Model"]-comp["Baseline"]).round(2)
            st.dataframe(comp, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Aktuální týmové statistiky")

# Dense current-season table
agg = latest.groupby("team").agg(
    Zápasy=("match_id","count"),
    Fauly=("fouls_committed","mean"),
    Fauly_proti=("fouls_suffered","mean"),
    Rohy=("corners_for","mean"),
    Rohy_proti=("corners_against","mean"),
    ŽK=("yellow_cards","mean"),
    Střely=("shots_for","mean"),
    Střely_na_bránu=("shots_on_target_for","mean"),
    Body=("points","sum"),
).reset_index().rename(columns={"team":"Tým"})

for c in ["Fauly","Fauly_proti","Rohy","Rohy_proti","ŽK","Střely","Střely_na_bránu"]:
    agg[c] = agg[c].round(2)

st.dataframe(
    agg.sort_values(["Body","Tým"], ascending=[False,True]),
    use_container_width=True,
    hide_index=True,
    height=700
)
