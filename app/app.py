from pathlib import Path
from datetime import date
import os,sys,subprocess
import joblib
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parent.parent
SCRIPTS=BASE/"scripts"; MODELS=BASE/"models"; TABLES=BASE/"data"/"tables"
sys.path.insert(0,str(SCRIPTS))
sys.path.insert(0,str(BASE/"app"))

from data_views import (latest_standings, build_cross_tab, build_referee_summary,
                       build_referee_detail, short_team_name, referee_cell_styles,
                       cross_tab_display, TEAM_COLUMNS, REF_COLUMNS)

from count_common import load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows
from score_round import score_fixtures
from update_fixtures import load_fixtures,current_round,sync_fixtures
from update_officials import sync_officials,referee_for_match,referee_choices
from match_analysis import analyze
from referee_impact import impact_lookup, referee_display, canonical_referee
from pattern_views import prematch_context, match_view, render_patterns

st.set_page_config(page_title="NABOMBI Skaut",page_icon="⚽",layout="wide",initial_sidebar_state="collapsed")

MARKETS=("fouls","corners","yellow_cards")
LABEL={"fouls":"Fauly","corners":"Rohy","yellow_cards":"ŽK",
       "fouls_total":"Fauly celkem","corners_total":"Rohy celkem",
       "yellow_cards_total":"Karty celkem"}
IS_CLOUD=bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_SERVER_HEADLESS"))

st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1200px}
[data-testid="stMetricValue"]{font-size:1.35rem}
.match-card{border:1px solid rgba(128,128,128,.25);border-radius:14px;padding:12px 14px;margin:8px 0}
.muted{opacity:.7;font-size:.9rem}
@media(max-width:700px){
 .block-container{padding-left:.65rem;padding-right:.65rem}
 h1{font-size:1.65rem!important}
 h2{font-size:1.3rem!important}
 [data-testid="stDataFrame"]{font-size:.82rem}
}
</style>
""",unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def history(contents):
    p=TABLES/"team_match_stats.csv"
    if not p.exists(): return pd.DataFrame()
    from io import BytesIO
    x=pd.read_csv(BytesIO(contents)); x["match_date"]=pd.to_datetime(x.match_date,errors="coerce")
    return x

@st.cache_data(show_spinner=False)
def referee_matches():
    p=TABLES/"referee_match_stats.csv"
    if not p.exists(): return pd.DataFrame()
    x=pd.read_csv(p); x["match_date"]=pd.to_datetime(x.match_date,errors="coerce")
    x["referee_key"]=x.referee.map(canonical_referee)
    return x

@st.cache_resource(show_spinner=False)
def models():
    out={}
    for m in MARKETS:
        p=MODELS/f"{m}_model.joblib"
        if p.exists(): out[m]=joblib.load(p)
    return out


def paired_bar_chart(df, index_col, col_a, col_b, label_a, label_b):
    plot=df[[index_col,col_a,col_b]].copy()
    plot[col_a]=pd.to_numeric(plot[col_a],errors="coerce").fillna(0)
    plot[col_b]=pd.to_numeric(plot[col_b],errors="coerce").fillna(0)
    labels=plot[index_col].astype(str).tolist()
    y=np.arange(len(plot)); height=.36
    fig_h=max(3.2, len(plot)*0.58+1.2)
    fig,ax=plt.subplots(figsize=(9,fig_h))
    ax.barh(y-height/2,plot[col_a].to_numpy(),height,label=label_a)
    ax.barh(y+height/2,plot[col_b].to_numpy(),height,label=label_b)
    ax.set_yticks(y); ax.set_yticklabels(labels,fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Počet"); ax.legend()
    ax.margins(y=.03)
    fig.tight_layout()
    st.pyplot(fig,use_container_width=True)
    plt.close(fig)

def pct(x): return f"{100*x:.0f}%"
def fmt_odds(x): return f"{x:.2f}" if np.isfinite(x) else "—"

def predict_one(home,away,match_date,season,referee):
    return score_fixtures([{
        "home_team":home,"away_team":away,"match_date":str(match_date),
        "season":season,"referee":referee
    }])

@st.cache_data(show_spinner=False, max_entries=32)
def cached_pattern_view(matches_csv, stats_csv, context):
    from io import BytesIO
    return match_view(pd.read_csv(BytesIO(matches_csv)),
                      pd.read_csv(BytesIO(stats_csv)), context)

def load_current_round_view(auto_sync=True):
    completed=H[(H.season==season)&(H.venue=="H")][["team","opponent"]].rename(columns={"team":"home_team","opponent":"away_team"})
    schedule=load_fixtures(season,auto_sync=auto_sync)
    rnd,view=current_round(schedule,completed)
    if auto_sync:
        try: sync_officials(rnd)
        except Exception: pass  # Existing cache remains available if synchronization fails.
    view=view.copy()
    view["_date"]=pd.to_datetime(view.match_date,errors="coerce")
    times=view.kickoff_time.fillna("").astype(str).str.strip()
    times=times.where(times.str.count(":")!=1,times+":00")
    view["_time"]=pd.to_timedelta(times,errors="coerce")
    return rnd,view.sort_values(["_date","_time"],kind="stable",na_position="last").reset_index(drop=True)


def clear_match_results():
    for key in list(st.session_state):
        if key in {"single","single_identity","single_version"}:
            del st.session_state[key]


def select_current_match():
    st.subheader("Zápas")
    try:
        rnd,view=load_current_round_view(auto_sync=False)
    except Exception as e:
        clear_match_results()
        st.warning(f"Rozpis aktuálního kola se nepodařilo načíst: {e}")
        st.stop()
    if view.empty:
        clear_match_results()
        st.warning("Rozpis aktuálního kola neobsahuje žádná utkání.")
        st.stop()
    if len(view)!=10:
        st.warning(f"Rozpis kola není kompletní: {len(view)}/10 zápasů.")
    options=list(zip(view.home_team,view.away_team))
    if len(set(options))!=len(options):
        clear_match_results()
        st.warning("Rozpis obsahuje nejednoznačná utkání. Výběr nyní není dostupný.")
        st.stop()
    st.caption(f"Kolo {rnd} · {season}")
    home,away=st.selectbox("Vyber zápas aktuálního kola",options,
                          format_func=lambda pair:f"{pair[0]} – {pair[1]}",
                          key=f"match_fixture_{season}_{rnd}")
    row=view[(view.home_team==home)&(view.away_team==away)].iloc[0]
    ref=referee_for_match(home,away,rnd)
    ref=str(ref).strip() if pd.notna(ref) else ""
    st.caption(f"Rozhodčí: {ref or 'Zatím neurčen'}")
    if pd.isna(row["_date"]):
        clear_match_results()
        st.warning("Datum utkání zatím není určeno. Výpočet bude dostupný po doplnění rozpisu.")
        st.stop()
    score_date=row["_date"].date()
    time=str(row.kickoff_time).strip() if pd.notna(row.kickoff_time) else ""
    st.caption(f"Termín: {score_date.strftime('%d.%m.%Y')} · {time or 'Čas neurčen'}")
    identity=(home,away,str(score_date),season,ref,rnd)
    if st.session_state.get("single_identity")!=identity:
        clear_match_results()
    return home,away,score_date,season,ref,rnd


H=history((TABLES/"team_match_stats.csv").read_bytes()) if (TABLES/"team_match_stats.csv").exists() else pd.DataFrame()
if H.empty:
    st.error("Chybí datové tabulky.")
    st.stop()
teams=sorted(H.team.dropna().unique())
season=sorted(H.season.dropna().unique())[-1]
ref_hist=sorted({canonical_referee(x) for x in H.referee.dropna().unique()})
REF_IMPACTS=impact_lookup(season)

st.title("⚽ NABOMBI Skaut")

nav=st.segmented_control("Pohled",["Kolo","Zápas","Cross-TAB","Rozhodčí","Týmy"],default="Kolo",label_visibility="collapsed")
if nav is None: nav="Kolo"

if nav=="Kolo":
    try:
        rnd,view=load_current_round_view()
    except Exception as e:
        st.error(f"Rozlosování se nepodařilo načíst: {e}"); st.stop()
    st.subheader(f"Kolo {rnd}")
    if len(view)!=10:
        st.warning(f"Rozpis kola není kompletní: {len(view)}/10 zápasů.")
    rows=[]
    for _,r in view.iterrows():
        ref=referee_for_match(r.home_team,r.away_team,rnd)
        day=r["_date"].strftime("%d.%m.%Y") if pd.notna(r["_date"]) else "Termín neurčen"
        time=str(r.kickoff_time).strip() if pd.notna(r.kickoff_time) else ""
        rows.append({"Datum / čas":f"{day} {time}".strip(),
                     "Domácí":r.home_team,"Hosté":r.away_team,
                     "Rozhodčí":str(ref).strip() if pd.notna(ref) and str(ref).strip() else "Zatím neurčen"})
    st.dataframe(pd.DataFrame(rows,columns=["Datum / čas","Domácí","Hosté","Rozhodčí"]),
                 hide_index=True,use_container_width=True,height=388,
                 column_config={
                     "Datum / čas":st.column_config.TextColumn(width=135),
                     "Domácí":st.column_config.TextColumn(width=120),
                     "Hosté":st.column_config.TextColumn(width=120),
                     "Rozhodčí":st.column_config.TextColumn(width=115),
                 })


elif nav=="Zápas":
    home,away,score_date,ss,ref,match_round=select_current_match()

    # Independent read-only context: never use a manually simulated model referee.
    try:
        pattern_schedule=pd.read_csv(BASE/"data"/"fixtures"/f"premier_league_{ss}.csv")
        officials_path=BASE/"data"/"fixtures"/f"match_officials_{ss}.csv"
        pattern_officials=pd.read_csv(officials_path) if officials_path.exists() else pd.DataFrame()
        pattern_context=prematch_context(pattern_schedule,pattern_officials,home,away,ss,
                                        str(score_date),pd.Timestamp.now(tz="UTC"))
        if pattern_context is not None:
            view=cached_pattern_view((TABLES/"matches.csv").read_bytes(),
                                     (TABLES/"team_match_stats.csv").read_bytes(),pattern_context)
            render_patterns(st,view)
            if not pattern_context["referee"]:
                st.caption("Rozhodčí není jednoznačně známý z delegace; zobrazujeme pouze týmové vzorce.")
        else:
            st.subheader("Vzorce")
            st.caption("Vzorce jsou dostupné pro jednoznačný budoucí zápas s časem výkopu v rozpisu.")
    except (OSError, ValueError, KeyError, TypeError):
        st.subheader("Vzorce")
        st.caption("Historické vzorce nyní nelze bezpečně načíst.")

    current_identity=(home,away,str(score_date),ss,ref,match_round)
    scored=None
    try:
        with st.spinner("Načítám analýzu…"):
            scored,version=analyze(BASE,home,away,score_date,ss,ref)
        if st.session_state.get("single_version")!=version:
            clear_match_results()
        for notice in scored.attrs.get("model_provenance", []):
            st.caption(notice)
        st.session_state.single=scored
        st.session_state.single_identity=current_identity
        st.session_state.single_version=version
    except FileNotFoundError as exc:
        clear_match_results()
        st.warning(f"Modelová analýza není dostupná. {exc}. Modely nebyly přetrénovány ani nahrazeny.")
    except Exception as exc:
        clear_match_results()
        st.warning(f"Analýzu se nepodařilo bezpečně načíst: {exc}")
    identity=st.session_state.get("single_identity")

    if isinstance(scored,pd.DataFrame) and len(scored) and identity==current_identity:
        # Compact expected-count overview, including match totals.
        preds=scored.groupby(["team","market"],as_index=False).prediction.first()
        for team in [home,away]:
            tx=preds[preds.team==team].set_index("market")
            cols=st.columns(3)
            for j,m in enumerate(MARKETS):
                val=tx.loc[m,"prediction"] if m in tx.index else np.nan
                cols[j].metric(f"{team} · {LABEL[m]}",f"{val:.2f}")

        totals=preds[preds.team=="CELKEM"].set_index("market")
        total_markets=["fouls_total","corners_total","yellow_cards_total"]
        cols=st.columns(3)
        for j,m in enumerate(total_markets):
            val=totals.loc[m,"prediction"] if m in totals.index else np.nan
            cols[j].metric(LABEL[m],f"{val:.2f}")

elif nav in {"Cross-TAB", "Rozhodčí"}:
    # Deliberately uncached: newly published CSVs are read on every rerun.
    try:
        current_history = pd.read_csv(TABLES/"team_match_stats.csv")
        view_season = sorted(current_history.season.dropna().astype(str).unique())[-1]
        st.subheader(nav)
        if nav == "Cross-TAB":
            standings = pd.read_csv(TABLES/"standings_history.csv")
            order = latest_standings(standings, view_season)
            controls = st.columns([2, 1])
            with controls[0]:
                selected = st.selectbox("Tým", [None, *order.team.tolist()],
                    format_func=lambda x: "Celkem" if x is None else short_team_name(x), key="cross_team")
            with controls[1]:
                split = st.segmented_control("Split", ["Doma", "Venku"], default="Doma", key="cross_venue")
            table = build_cross_tab(current_history, standings, view_season, selected,
                                    "A" if split == "Venku" else "H")
            as_of = table.attrs["as_of_date"]
            st.caption(f"Sezona {view_season} · Tabulka k {as_of.day}. {as_of.month}. {as_of.year} · odvozena z našich výsledkových dat")
            st.caption("+ tým · − soupeř · Doma/Venku se vztahuje k vybranému týmu. — = nedostupný zápas nebo statistika.")
            if len(table) != 20:
                st.warning("Pořadí zatím neobsahuje všech 20 týmů.")
            if table.attrs["excluded_rows"]:
                st.caption("Nejednoznačné nebo nekonzistentní zápasy jsou vynechány.")
            st.dataframe(cross_tab_display(table, selected),
                use_container_width=True, hide_index=True, height=740,
                column_config={"#": st.column_config.NumberColumn("#", width=30, format="%d"),
                               "Tým": st.column_config.TextColumn("Tým", width=105),
                               **{c: st.column_config.TextColumn(c, width=37) for c in TEAM_COLUMNS}})
        else:
            from referee_views import render_referees
            render_referees(st, pd.read_csv(TABLES/"matches.csv"), current_history,
                            canonical_referee, short_team_name)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        st.warning(f"Analytický pohled není dostupný: {exc}")

elif nav=="Týmy":
    st.subheader("Týmy")
    try:
        from team_views import render_teams
        render_teams(st, pd.read_csv(TABLES/"matches.csv"), pd.read_csv(TABLES/"team_match_stats.csv"))
    except (OSError, ValueError, KeyError, IndexError) as exc:
        st.warning(f"Týmový přehled není dostupný: {exc}")

