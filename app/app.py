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
from score_round import score_fixtures

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
    out={}
    for market in MARKETS:
        p=MODELS/f"{market}_model.joblib"
        if p.exists():
            out[market]=joblib.load(p)
    return out

def pct(x): return f"{100*x:.1f}%"
def odds(x): return f"{x:.2f}" if np.isfinite(x) else "—"

def predict_fixture(home, away, match_date, season, referee):
    fixture = build_fixture_rows(home, away, referee, str(match_date), season)
    models = load_models()
    records = []
    for market in MARKETS:
        if market not in models: continue
        art=models[market]; cfg=art["config"]
        for c in cfg["features"]:
            if c not in fixture.columns: fixture[c]=np.nan
        pred,extra,baseline=ensemble_prediction(
            art["model"],fixture,art["train_mean"],cfg
        )
        for i,row in fixture.iterrows():
            rec={
                "Tým":row["team"],"H/A":row["venue"],"Trh":MARKET_LABEL[market],
                "Predikce":round(float(pred[i]),2),
                "Model":round(float(extra[i]),2),
                "Baseline":round(float(baseline[i]),2),
            }
            for line in cfg["over_lines"]:
                p=float(over_probability([pred[i]],line,cfg)[0])
                rec[f"O {line}"]=p
                rec[f"Fair O {line}"]=float(fair_odds([p])[0])
            records.append(rec)
    return pd.DataFrame(records)

def compact_market_table(pred, market):
    x=pred[pred["Trh"]==MARKET_LABEL[market]].copy()
    if x.empty: return x
    cfg=load_config(market)
    cols=["Tým","H/A","Predikce"]
    for line in cfg["over_lines"]:
        cols += [f"O {line}",f"Fair O {line}"]
    x=x[cols]
    for line in cfg["over_lines"]:
        x[f"O {line}"]=x[f"O {line}"].map(pct)
        x[f"Fair O {line}"]=x[f"Fair O {line}"].map(odds)
    return x

def make_round_summary(scored, min_prob, selected_market):
    x=scored.copy()
    if selected_market!="Vše":
        reverse={v:k for k,v in MARKET_LABEL.items()}
        x=x[x.market==reverse[selected_market]]
    x=x[x.p_over>=min_prob]
    x["Zápas"]=x["home_team"]+" – "+x["away_team"]
    x["Výběr"]=x["team"]+" O"+x["line"].astype(str)+" "+x["market_label"]
    x["Predikce"]=x["prediction"].round(2)
    x["Pravděpodobnost"]=x["p_over"].map(pct)
    x["Fair kurz"]=x["fair_over"].round(2)
    x["Edge model-baseline"]=(x["model_component"]-x["baseline_component"]).round(2)
    cols=["Zápas","Výběr","Predikce","Pravděpodobnost","Fair kurz","Edge model-baseline"]
    return x.sort_values(["p_over","fair_over"],ascending=[False,True])[cols]

st.title("PL Analytika 2.0")
st.caption("Tabulkový dashboard · minimum klikání · maximum dat")

history=load_team_history()
models=load_models()
if history.empty:
    st.error("Chybí data/tables/team_match_stats.csv. Spusť setup_and_run.bat nebo update_and_train.bat.")
    st.stop()

teams=sorted(history["team"].dropna().unique())
last_season=sorted(history["season"].dropna().unique())[-1]

page=st.sidebar.radio("Pohled",["Hrací kolo","Jeden zápas","Týmy"],index=0)

if page=="Hrací kolo":
    st.header("Hrací kolo")
    st.caption("Nahraj nebo vlož seznam zápasů. Aplikace spočítá všechny trhy najednou.")

    col1,col2,col3=st.columns([2,1,1])
    with col1:
        uploaded=st.file_uploader("Fixtures CSV",type=["csv"])
    with col2:
        min_prob=st.slider("Min. Over pravděpodobnost",0.50,0.95,0.65,0.01)
    with col3:
        market_filter=st.selectbox("Trh",["Vše","Fauly","Rohy","ŽK"])

    if uploaded is not None:
        fixtures=pd.read_csv(uploaded).fillna("")
    else:
        st.info("CSV má sloupce: home_team, away_team, match_date, season, referee. Šablona je v data/fixtures/fixtures_template.csv.")
        fixtures=pd.DataFrame(columns=["home_team","away_team","match_date","season","referee"])

    if not fixtures.empty:
        st.subheader("Zadané zápasy")
        st.dataframe(fixtures,use_container_width=True,hide_index=True)

        if st.button("Spočítat celé kolo",type="primary"):
            with st.spinner("Skóruji všechny zápasy…"):
                scored=score_fixtures(fixtures.to_dict("records"))
                st.session_state["round_scored"]=scored

    scored=st.session_state.get("round_scored")
    if isinstance(scored,pd.DataFrame) and not scored.empty:
        st.subheader("Nejvyšší modelové pravděpodobnosti")
        summary=make_round_summary(scored,min_prob,market_filter)
        st.dataframe(summary,use_container_width=True,hide_index=True,height=650)

        st.download_button(
            "Stáhnout kompletní výstup CSV",
            scored.to_csv(index=False).encode("utf-8-sig"),
            file_name="round_predictions.csv",
            mime="text/csv"
        )

        st.subheader("Souhrn zápasů")
        best=scored.sort_values("p_over",ascending=False).groupby(
            ["home_team","away_team","team","market"],as_index=False
        ).first()
        best["Zápas"]=best.home_team+" – "+best.away_team
        best["Trh"]=best.market.map(MARKET_LABEL)
        best["Nejlepší O"]=best.line
        best["P"]=best.p_over.map(pct)
        best["Fair"]=best.fair_over.round(2)
        best["Predikce"]=best.prediction.round(2)
        st.dataframe(
            best[["Zápas","team","Trh","Predikce","Nejlepší O","P","Fair"]],
            use_container_width=True,hide_index=True
        )

elif page=="Jeden zápas":
    st.header("Jeden zápas")
    c1,c2,c3,c4,c5=st.columns([1.3,1.3,1,1,1.4])
    with c1: home=st.selectbox("Domácí",teams,index=0)
    with c2:
        away_opts=[t for t in teams if t!=home]
        away=st.selectbox("Hosté",away_opts,index=min(1,len(away_opts)-1))
    with c3: season=st.text_input("Sezóna",value=last_season)
    with c4: match_date=st.date_input("Datum",value=date.today())
    with c5: referee=st.text_input("Rozhodčí",value="",placeholder="volitelné")

    if st.button("Spočítat zápas",type="primary"):
        pred=predict_fixture(home,away,match_date,season,referee)
        st.session_state["single_pred"]=pred

    pred=st.session_state.get("single_pred")
    if isinstance(pred,pd.DataFrame) and not pred.empty:
        summary=pred.pivot(index="Tým",columns="Trh",values="Predikce").reset_index()
        ordered=["Tým"]+[c for c in ["Fauly","Rohy","ŽK"] if c in summary.columns]
        st.dataframe(summary[ordered],use_container_width=True,hide_index=True)

        tabs=st.tabs(["Fauly","Rohy","Žluté karty","Model vs baseline"])
        with tabs[0]:
            st.dataframe(compact_market_table(pred,"fouls"),use_container_width=True,hide_index=True)
        with tabs[1]:
            st.dataframe(compact_market_table(pred,"corners"),use_container_width=True,hide_index=True)
        with tabs[2]:
            st.dataframe(compact_market_table(pred,"yellow_cards"),use_container_width=True,hide_index=True)
        with tabs[3]:
            comp=pred[["Tým","Trh","Predikce","Model","Baseline"]].copy()
            comp["Rozdíl"]=(comp.Model-comp.Baseline).round(2)
            st.dataframe(comp,use_container_width=True,hide_index=True)

else:
    st.header("Týmové statistiky")
    latest=history[history.season==last_season].copy()
    agg=latest.groupby("team").agg(
        Zápasy=("match_id","count"),Fauly=("fouls_committed","mean"),
        Fauly_proti=("fouls_suffered","mean"),Rohy=("corners_for","mean"),
        Rohy_proti=("corners_against","mean"),ŽK=("yellow_cards","mean"),
        Střely=("shots_for","mean"),Střely_na_bránu=("shots_on_target_for","mean"),
        Body=("points","sum")
    ).reset_index().rename(columns={"team":"Tým"})
    for c in ["Fauly","Fauly_proti","Rohy","Rohy_proti","ŽK","Střely","Střely_na_bránu"]:
        agg[c]=agg[c].round(2)
    st.dataframe(
        agg.sort_values(["Body","Tým"],ascending=[False,True]),
        use_container_width=True,hide_index=True,height=760
    )

with st.sidebar:
    st.divider()
    if st.button("Obnovit data + modely",use_container_width=True):
        with st.spinner("Aktualizuji…"):
            p1=subprocess.run([sys.executable,str(SCRIPTS/"update_data.py"),"--download-current"],
                              cwd=BASE,capture_output=True,text=True)
            if p1.returncode:
                st.error(p1.stderr[-1200:])
            else:
                p2=subprocess.run([sys.executable,str(SCRIPTS/"train_count_models.py")],
                                  cwd=BASE,capture_output=True,text=True)
                if p2.returncode:
                    st.error(p2.stderr[-1200:])
                else:
                    st.cache_data.clear(); st.cache_resource.clear()
                    st.success("Data i modely aktualizovány.")
