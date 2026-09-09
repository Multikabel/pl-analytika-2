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

from count_common import load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows
from score_round import score_fixtures
from update_fixtures import load_fixtures,current_round,sync_fixtures
from update_officials import sync_officials,referee_for_match,referee_choices
from prediction_archive import load_log, archive_selected_predictions, settle_predictions, summary_stats
from model_prediction_stats import load_log as load_model_prediction_log, summary as model_prediction_summary, snapshot as snapshot_model_predictions
from referee_impact import impact_lookup, referee_display, canonical_referee

st.set_page_config(page_title="PL Analytika 2.0",page_icon="⚽",layout="wide",initial_sidebar_state="collapsed")

MARKETS=("fouls","corners","yellow_cards")
LABEL={"fouls":"Fauly","corners":"Rohy","yellow_cards":"ŽK",
       "fouls_total":"Fauly celkem","corners_total":"Rohy celkem",
       "yellow_cards_total":"Karty celkem"}
IS_CLOUD=bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_SERVER_HEADLESS"))

# Persistent manual tips on Streamlit Cloud.
try:
    if "github" in st.secrets:
        if st.secrets["github"].get("token"):
            os.environ["PL_ANALYTIKA_GITHUB_TOKEN"]=st.secrets["github"]["token"]
        os.environ["PL_ANALYTIKA_GITHUB_REPO"]=st.secrets["github"].get("repo","Multikabel/pl-analytika-2")
        os.environ["PL_ANALYTIKA_GITHUB_BRANCH"]=st.secrets["github"].get("branch","main")
except Exception:
    pass


st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1200px}
[data-testid="stMetricValue"]{font-size:1.35rem}
.match-card{border:1px solid rgba(128,128,128,.25);border-radius:14px;padding:12px 14px;margin:8px 0}
.muted{opacity:.7;font-size:.9rem}
.tip{font-size:1.02rem;font-weight:650}
@media(max-width:700px){
 .block-container{padding-left:.65rem;padding-right:.65rem}
 h1{font-size:1.65rem!important}
 h2{font-size:1.3rem!important}
 [data-testid="stDataFrame"]{font-size:.82rem}
}
</style>
""",unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def history():
    p=TABLES/"team_match_stats.csv"
    if not p.exists(): return pd.DataFrame()
    x=pd.read_csv(p); x["match_date"]=pd.to_datetime(x.match_date,errors="coerce")
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
    x=np.arange(len(plot)); width=.38
    fig,ax=plt.subplots(figsize=(max(8,len(plot)*0.52),4.2))
    ax.bar(x-width/2,plot[col_a].to_numpy(),width,label=label_a)
    ax.bar(x+width/2,plot[col_b].to_numpy(),width,label=label_b)
    ax.set_xticks(x); ax.set_xticklabels(labels,rotation=65,ha="right",fontsize=8)
    ax.set_ylabel("Počet"); ax.legend(); ax.margins(x=.01)
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

def best_high_odds_lines(scored,min_fair=2.0):
    # Until bookmaker odds are connected, this filter is explicitly on MODEL FAIR ODDS.
    x=scored[scored.fair_over>=min_fair].copy()
    if x.empty:return x
    # For each team/market select the highest probability line that still has fair >= threshold.
    x=x.sort_values(["team","market","p_over"],ascending=[True,True,False])
    x=x.groupby(["team","market"],as_index=False).first()
    return x.sort_values("p_over",ascending=False)

def display_tip_table(x):
    if x.empty:
        st.info("Pro zvolený filtr nejsou žádné modelové kandidáty.")
        return
    out=pd.DataFrame({
        "Tým":x.team,
        "Trh":x.market.map(LABEL),
        "Tip":["O"+str(v) for v in x.line],
        "Pred.":x.prediction.round(2),
        "P":x.p_over.map(pct),
        "Fair":x.fair_over.round(2),
    })
    st.dataframe(out,use_container_width=True,hide_index=True)


def selectable_tip_table(x,key_prefix):
    if x is None or x.empty:
        st.info("Pro zvolený filtr nejsou žádní kandidáti.")
        return pd.DataFrame()

    raw=x.reset_index(drop=True).copy()
    view=pd.DataFrame({
        "Uložit":[False]*len(raw),
        "Kurz":[np.nan]*len(raw),
        "Tým":raw.team,
        "Trh":raw.market.map(LABEL),
        "Tip":"O"+raw.line.astype(str),
        "Pred.":pd.to_numeric(raw.prediction,errors="coerce").round(2),
        "P":pd.to_numeric(raw.p_over,errors="coerce").map(pct),
        "Fair":pd.to_numeric(raw.fair_over,errors="coerce").round(2),
    })

    edited=st.data_editor(
        view,
        use_container_width=True,
        hide_index=True,
        key=f"pick_{key_prefix}",
        disabled=["Tým","Trh","Tip","Pred.","P","Fair"],
        column_config={
            "Uložit":st.column_config.CheckboxColumn("✓",help="Zaškrtni jen tipy, které chceš sledovat."),
            "Kurz":st.column_config.NumberColumn(
                "Aktuální kurz",
                min_value=1.01,
                max_value=100.0,
                step=0.01,
                format="%.2f",
                help="Sem zadej skutečný kurz ze sázkovky."
            ),
        },
    )

    mask=edited["Uložit"].fillna(False).astype(bool).to_numpy()
    chosen=raw.loc[mask].copy()

    if len(chosen):
        chosen["bookmaker_odds"]=pd.to_numeric(
            edited.loc[mask,"Kurz"].reset_index(drop=True),errors="coerce"
        ).to_numpy()
        chosen["stake_units"]=1.0

    return chosen

H=history()
if H.empty:
    st.error("Chybí datové tabulky.")
    st.stop()
teams=sorted(H.team.dropna().unique())
season=sorted(H.season.dropna().unique())[-1]
ref_hist=sorted({canonical_referee(x) for x in H.referee.dropna().unique()})
REF_IMPACTS=impact_lookup(season)

st.title("⚽ PL Analytika 2.0")

nav=st.segmented_control("Pohled",["Kolo","Zápas","Tipy","Statistiky","Data"],default="Kolo",label_visibility="collapsed")
if nav is None: nav="Kolo"

with st.expander("⚙️ Filtry",expanded=False):
    min_fair=st.number_input(
        "Minimální modelový fair kurz",
        min_value=1.20,max_value=10.0,value=2.00,step=.05,
        help="Dokud nepřipojíme skutečné bookmaker kurzy, filtrujeme modelový fair kurz. Bookmaker kurz ≥ 2,00 bude v další value vrstvě."
    )
    st.caption("🎯 Tvoje výchozí preference je 2,00+. Skutečný bookmaker kurz zatím není napojený, proto je sloupec označen jako Fair.")

if nav=="Kolo":
    completed=H[(H.season==season)&(H.venue=="H")][["team","opponent"]].rename(columns={"team":"home_team","opponent":"away_team"})
    try:
        schedule=load_fixtures(season,auto_sync=True)
        rnd,round_df=current_round(schedule,completed)
        try: sync_officials(rnd)
        except Exception: pass
    except Exception as e:
        st.error(f"Rozlosování se nepodařilo načíst: {e}"); st.stop()

    d1=pd.to_datetime(round_df.match_date).min().strftime("%d.%m.")
    d2=pd.to_datetime(round_df.match_date).max().strftime("%d.%m.")
    c1,c2,c3=st.columns(3)
    c1.metric("Kolo",rnd); c2.metric("Termín",f"{d1}–{d2}"); c3.metric("Zbývá",int((~round_df.played).sum()))

    future=round_df[~round_df.played].copy()
    if len(future):
        if st.button("⚡ Spočítat zbývající zápasy",type="primary",use_container_width=True):
            fixtures=[]
            for _,r in future.iterrows():
                ref=referee_for_match(r.home_team,r.away_team,rnd)
                fixtures.append({"home_team":r.home_team,"away_team":r.away_team,
                                 "match_date":r.match_date,"season":season,"referee":ref})
            with st.spinner("Počítám celé kolo…"):
                st.session_state.round_score=score_fixtures(fixtures)
                st.session_state.round_no=rnd
                try:
                    added_stats=snapshot_model_predictions(
                        st.session_state.round_score,
                        match_round=rnd,
                        model_version="count-models-v1.6",
                    )
                    if added_stats:
                        st.toast(f"Do Statistik uloženo {added_stats} nových predikcí.")
                except Exception as e:
                    st.warning(f"Predikce byly spočítány, ale nepodařilo se uložit Statistiky: {e}")

    score=st.session_state.get("round_score")
    selected_parts=[]
    for _,r in round_df.iterrows():
        ref=referee_for_match(r.home_team,r.away_team,rnd)
        status="✅ Odehráno" if r.played else "🕒 Čeká"
        st.markdown(
            f'<div class="match-card"><b>{r.home_team} – {r.away_team}</b><br>'
            f'<span class="muted">{pd.to_datetime(r.match_date).strftime("%d.%m. %Y")} · '
            f'{r.kickoff_time if pd.notna(r.kickoff_time) and r.kickoff_time else ""} · {status}<br>'
            f'👨‍⚖️ {referee_display(ref,REF_IMPACTS)}</span></div>',
            unsafe_allow_html=True
        )
        if isinstance(score,pd.DataFrame) and st.session_state.get("round_no")==rnd and not r.played:
            sx=score[(score.home_team==r.home_team)&(score.away_team==r.away_team)]
            cand=best_high_odds_lines(sx,min_fair)
            picked=selectable_tip_table(cand,f"{rnd}_{r.home_team}_{r.away_team}")
            if len(picked): selected_parts.append(picked)

    if isinstance(score,pd.DataFrame) and st.session_state.get("round_no")==rnd:
        chosen=pd.concat(selected_parts,ignore_index=True) if selected_parts else pd.DataFrame()
        invalid_odds = (
            len(chosen)>0 and
            ("bookmaker_odds" not in chosen.columns or
             pd.to_numeric(chosen["bookmaker_odds"],errors="coerce").isna().any() or
             (pd.to_numeric(chosen["bookmaker_odds"],errors="coerce")<=1.0).any())
        )
        st.divider()
        st.caption(f"Vybráno: {len(chosen)}. U každého uloženého tipu musí být zadaný skutečný kurz.")
        if invalid_odds:
            st.warning("Doplň aktuální kurz u všech zaškrtnutých tipů.")
        if st.button(f"💾 Uložit vybrané tipy ({len(chosen)})",type="primary",
                     use_container_width=True,disabled=(len(chosen)==0 or invalid_odds)):
            added=archive_selected_predictions(chosen,rnd,"count-models-v1.1","manual")
            if added: st.success(f"Uloženo {added} nových tipů včetně skutečných kurzů.")
            else: st.info("Vybrané tipy už jsou uložené.")


elif nav=="Zápas":
    c1,c2=st.columns(2)
    home=c1.selectbox("Domácí",teams)
    away_opts=[t for t in teams if t!=home]
    away=c2.selectbox("Hosté",away_opts)
    c3,c4=st.columns(2)
    md=c3.date_input("Datum",value=date.today())
    ss=c4.text_input("Sezóna",season)

    auto_ref=""
    match_round=None
    try:
        sch=load_fixtures(ss,auto_sync=False)
        # Prefer exact fixture identity; date can move after TV scheduling.
        q=sch[(sch.home_team==home)&(sch.away_team==away)]
        if len(q):
            row=q.iloc[0]
            match_round=int(row.match_round)
            # Keep the official schedule date synced into the scoring identity.
            official_date=pd.to_datetime(row.match_date).date()
            if md != official_date:
                st.caption(f"ℹ️ Rozpis: {official_date.strftime('%d.%m.%Y')} · kolo {match_round}")
            try: sync_officials(match_round)
            except Exception: pass
            auto_ref=referee_for_match(home,away,match_round)
    except Exception:
        pass

    score_date=official_date if "official_date" in locals() and match_round is not None else md
    choices=referee_choices(ref_hist,auto_ref)
    if auto_ref:
        ref=st.selectbox("Rozhodčí",choices,index=choices.index(auto_ref),
                         format_func=lambda x: referee_display(x,REF_IMPACTS),
                         help="Automaticky načtený z delegace. Můžeš ho ručně změnit.")
        st.caption("✓ Rozhodčí doplněn automaticky")
    else:
        opts=["— zatím neurčen —"]+choices
        selected=st.selectbox("Rozhodčí",opts,index=0,format_func=lambda x: x if x.startswith("—") else referee_display(x,REF_IMPACTS))
        ref="" if selected.startswith("—") else selected
        st.caption("Delegace zatím nebyla nalezena. Model použije neutrální doplnění chybějících referee metrik.")

    if st.button("Spočítat zápas",type="primary",use_container_width=True):
        with st.spinner("Počítám…"):
            st.session_state.single=predict_one(home,away,score_date,ss,ref)
            st.session_state.single_identity=(home,away,str(score_date),ss,ref,match_round)
            try:
                round_for_stats=match_round if match_round is not None else 0
                added_stats=snapshot_model_predictions(
                    st.session_state.single,
                    match_round=round_for_stats,
                    model_version="count-models-v1.6",
                )
                if added_stats:
                    st.toast(f"Do Statistik uloženo {added_stats} predikcí tohoto zápasu.")
                else:
                    st.toast("Predikce tohoto zápasu už jsou ve Statistikách.")
            except Exception as e:
                st.warning(f"Zápas byl spočítán, ale nepodařilo se uložit Statistiky: {e}")

    scored=st.session_state.get("single")
    identity=st.session_state.get("single_identity")
    current_identity=(home,away,str(score_date),ss,ref,match_round)

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

        st.subheader("Hlavní kandidáti")
        main=best_high_odds_lines(scored,min_fair)
        display_tip_table(main)
        st.caption("Hlavní kandidáti jsou jen rychlý přehled. Tip můžeš uložit z libovolné půlbodové hranice níže.")

        st.subheader("Vybrat tip")
        f1,f2=st.columns(2)
        market_options=list(LABEL.keys())
        chosen_market=f1.selectbox(
            "Trh",
            market_options,
            format_func=lambda m: LABEL[m],
            key="single_market_filter",
        )

        market_rows=scored[scored.market==chosen_market].copy()
        team_values=market_rows.team.dropna().unique().tolist()
        if len(team_values)>1:
            chosen_team=f2.selectbox(
                "Tým",
                team_values,
                format_func=lambda x: "Celý zápas" if x=="CELKEM" else x,
                key="single_team_filter",
            )
            market_rows=market_rows[market_rows.team==chosen_team]
        else:
            chosen_team=team_values[0] if team_values else ""
            f2.text_input(
                "Výběr",
                value=("Celý zápas" if chosen_team=="CELKEM" else chosen_team),
                disabled=True,
            )

        market_rows=market_rows.sort_values("line").reset_index(drop=True)
        if len(market_rows):
            # One editable table exposes every available line for the selected market.
            picked=selectable_tip_table(
                market_rows,
                f"single_{home}_{away}_{chosen_market}_{chosen_team}"
            )

            invalid_odds=(
                len(picked)>0 and
                ("bookmaker_odds" not in picked.columns or
                 pd.to_numeric(picked["bookmaker_odds"],errors="coerce").isna().any() or
                 (pd.to_numeric(picked["bookmaker_odds"],errors="coerce")<=1.0).any())
            )

            if invalid_odds:
                st.warning("Doplň aktuální kurz u všech zaškrtnutých tipů.")

            if st.button(
                f"💾 Uložit vybrané tipy ({len(picked)})",
                type="primary",
                use_container_width=True,
                disabled=(len(picked)==0 or invalid_odds),
                key="save_single_tips",
            ):
                # Ensure archive identity is complete even though score_fixture already carries it.
                picked=picked.copy()
                picked["home_team"]=home
                picked["away_team"]=away
                picked["match_date"]=str(score_date)
                picked["season"]=ss
                picked["referee"]=ref
                round_to_save=match_round if match_round is not None else 0
                added=archive_selected_predictions(
                    picked,
                    match_round=round_to_save,
                    model_version="count-models-v1.3",
                    selection_source="manual_match",
                )
                if added:
                    st.success(f"Uloženo {added} nových tipů ze stránky Zápas.")
                else:
                    st.info("Vybrané tipy už jsou ve statistice uložené.")

        with st.expander("Všechny hranice – přehled"):
            out=scored.copy()
            out["Trh"]=out.market.map(LABEL)
            out["Výběr"]=out.team.map(lambda x:"Celý zápas" if x=="CELKEM" else x)
            out["Tip"]="O"+out.line.astype(str)
            out["Pred."]=pd.to_numeric(out.prediction,errors="coerce").round(2)
            out["P"]=out.p_over.map(pct)
            out["Fair"]=out.fair_over.round(2)
            st.dataframe(
                out[["Výběr","Trh","Tip","Pred.","P","Fair"]],
                use_container_width=True,
                hide_index=True,
            )

elif nav=="Tipy":
    st.subheader("📈 Statistika tipů")
    # Settle whenever the page is opened; harmless/idempotent if nothing new exists.
    try:
        settle_predictions()
    except Exception:
        pass
    log=load_log()
    stats=summary_stats(log)

    c1,c2,c3,c4=st.columns(4)
    c1.metric("Tipů",stats["tips"])
    c2.metric("Úspěšnost",f'{100*stats["hit_rate"]:.1f}%' if pd.notna(stats["hit_rate"]) else "—")
    c3.metric("Prům. kurz",f'{stats["avg_bookmaker_odds"]:.2f}' if pd.notna(stats["avg_bookmaker_odds"]) else "—")
    c4.metric("Zisk",f'{stats["profit_units"]:+.2f} u')

    c5,c6,c7=st.columns(3)
    c5.metric("Výher",stats["wins"])
    c6.metric("Proher",stats["losses"])
    c7.metric("ROI",f'{100*stats["roi"]:+.1f}%' if pd.notna(stats["roi"]) else "—")

    settled=log[log["status"].eq("settled")].copy()
    pending=log[log["status"].eq("pending")].copy()

    if len(settled):
        st.caption(f'Průměrný modelový fair kurz vyhodnocených tipů: {stats["avg_fair"]:.2f}')

        by_market=[]
        for market,g in settled.groupby("market"):
            wins=(g.result=="WIN").sum()
            stake=pd.to_numeric(g.get("stake_units",pd.Series(1.0,index=g.index)),errors="coerce").fillna(1.0)
            profit=pd.to_numeric(g.get("profit_units",pd.Series(0.0,index=g.index)),errors="coerce").fillna(0)
            total_stake=float(stake.sum())
            total_profit=float(profit.sum())
            by_market.append({
                "Trh":LABEL.get(market,market),
                "Tipů":len(g),
                "Výher":int(wins),
                "Úspěšnost":f"{100*wins/len(g):.1f}%",
                "Prům. kurz":round(pd.to_numeric(g.get("bookmaker_odds",pd.Series(index=g.index,dtype=float)),errors="coerce").mean(),2),
                "Zisk":round(total_profit,2),
                "ROI":f"{100*total_profit/total_stake:+.1f}%" if total_stake else "—",
            })
        st.dataframe(pd.DataFrame(by_market),use_container_width=True,hide_index=True)

        st.subheader("Historie")
        h=settled.sort_values(["match_date","created_at"],ascending=False).copy()
        h["Zápas"]=h.home_team+" – "+h.away_team
        h["Tip"]=h.team+" O"+h.line.astype(str)+" "+h.market.map(LABEL)
        h["Fair"]=pd.to_numeric(h.fair_over,errors="coerce").round(2)
        h["Kurz"]=pd.to_numeric(h.get("bookmaker_odds",pd.Series(index=h.index,dtype=float)),errors="coerce").round(2)
        h["P"]=pd.to_numeric(h.p_over,errors="coerce").map(lambda x:f"{100*x:.0f}%")
        h["Skutečnost"]=pd.to_numeric(h.actual_value,errors="coerce")
        h["Zisk"]=pd.to_numeric(h.get("profit_units",pd.Series(index=h.index,dtype=float)),errors="coerce").map(lambda x:f"{x:+.2f} u" if pd.notna(x) else "—")
        h["Výsledek"]=h.result.map({"WIN":"✅","LOSS":"❌"}).fillna(h.result)
        st.dataframe(
            h[["match_date","Zápas","Tip","P","Fair","Kurz","Skutečnost","Výsledek","Zisk"]],
            use_container_width=True,hide_index=True,height=600
        )
    else:
        st.info("Zatím není vyhodnocený žádný archivovaný tip.")

    if len(pending):
        with st.expander(f"Čekající tipy ({len(pending)})"):
            p=pending.copy()
            p["Zápas"]=p.home_team+" – "+p.away_team
            p["Tip"]=p.team+" O"+p.line.astype(str)+" "+p.market.map(LABEL)
            p["P"]=pd.to_numeric(p.p_over,errors="coerce").map(lambda x:f"{100*x:.0f}%")
            p["Fair"]=pd.to_numeric(p.fair_over,errors="coerce").round(2)
            p["Kurz"]=pd.to_numeric(p.get("bookmaker_odds",pd.Series(index=p.index,dtype=float)),errors="coerce").round(2)
            st.dataframe(
                p[["match_date","Zápas","Tip","P","Fair","Kurz"]],
                use_container_width=True,hide_index=True
            )

    st.caption("Statistika obsahuje pouze ručně vybrané a uložené tipy. Změna filtru ani nové přepočítání kola nic nepřidá. Po zápase se původní snapshot pouze vyhodnotí WIN/LOSS.")

elif nav=="Statistiky":
    st.subheader("📊 Úspěšnost predikcí")
    st.caption("Predikce se uloží automaticky při výpočtu jednoho zápasu i celého kola. Opakovaný výpočet stejného zápasu nevytváří duplicity.")
    plog=load_model_prediction_log()
    ps=model_prediction_summary(plog)

    c1,c2,c3,c4=st.columns(4)
    c1.metric("Vyhodnoceno",ps["n"])
    c2.metric("Over HIT",f'{100*ps["hit_rate"]:.1f}%' if pd.notna(ps["hit_rate"]) else "—")
    c3.metric("MAE",f'{ps["mae"]:.2f}' if pd.notna(ps["mae"]) else "—")
    c4.metric("Bias",f'{ps["bias"]:+.2f}' if pd.notna(ps["bias"]) else "—")

    c5,c6=st.columns(2)
    c5.metric("Model podstřelil",f'{100*ps["under_rate"]:.1f}%' if pd.notna(ps["under_rate"]) else "—")
    c6.metric("Model přestřelil",f'{100*ps["over_rate"]:.1f}%' if pd.notna(ps["over_rate"]) else "—")

    st.caption("Bias = skutečnost − predikce. Kladný bias znamená, že model dlouhodobě podstřeluje; záporný bias znamená přestřelování.")

    settled=plog[plog["status"].eq("settled")].copy()
    if len(settled):
        rows=[]
        for market,g in settled.groupby("market"):
            err=pd.to_numeric(g.error,errors="coerce")
            rows.append({
                "Trh":LABEL.get(market,market),
                "N":len(g),
                "Over HIT":f"{100*(g.result=='HIT').mean():.1f}%",
                "MAE":round(pd.to_numeric(g.abs_error,errors="coerce").mean(),2),
                "Bias":round(err.mean(),2),
                "Podstřeleno":f"{100*(err>0).mean():.1f}%",
                "Přestřeleno":f"{100*(err<0).mean():.1f}%",
                "Pred. Ø":round(pd.to_numeric(g.prediction,errors="coerce").mean(),2),
                "Skuteč. Ø":round(pd.to_numeric(g.actual_value,errors="coerce").mean(),2),
            })
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

        st.subheader("Historie predikcí")
        h=settled.sort_values(["match_date","created_at"],ascending=False).copy()
        h["Zápas"]=h.home_team+" – "+h.away_team
        h["Výběr"]=h.team.map(lambda x:"Celý zápas" if x=="CELKEM" else x)
        h["Trh"]=h.market.map(LABEL)
        h["Pred."]=pd.to_numeric(h.prediction,errors="coerce").round(2)
        h["Test"]="O"+pd.to_numeric(h.test_line,errors="coerce").map(lambda x:f"{x:.1f}")
        h["Skuteč."]=pd.to_numeric(h.actual_value,errors="coerce")
        h["Chyba"]=pd.to_numeric(h.error,errors="coerce").round(2)
        h["Výsledek"]=h.result.map({"HIT":"✅","MISS":"❌"})
        st.dataframe(
            h[["match_date","Zápas","Výběr","Trh","Pred.","Test","Skuteč.","Chyba","bias_direction","Výsledek"]],
            use_container_width=True,hide_index=True,height=620
        )
    else:
        st.info("Zatím nejsou vyhodnocené žádné automaticky archivované predikce.")

    pending=plog[plog["status"].eq("pending")].copy()
    if len(pending):
        with st.expander(f"Čekající predikce ({len(pending)})"):
            p=pending.copy()
            p["Zápas"]=p.home_team+" – "+p.away_team
            p["Výběr"]=p.team.map(lambda x:"Celý zápas" if x=="CELKEM" else x)
            p["Trh"]=p.market.map(LABEL)
            p["Pred."]=pd.to_numeric(p.prediction,errors="coerce").round(2)
            p["Test"]="O"+pd.to_numeric(p.test_line,errors="coerce").map(lambda x:f"{x:.1f}")
            st.dataframe(p[["match_date","Zápas","Výběr","Trh","Pred.","Test"]],
                         use_container_width=True,hide_index=True)

elif nav=="Data":
    st.subheader("🗂️ Data")
    st.caption(f"Aktuální sezóna {season} · bez historických sezón")
    data_mode=st.segmented_control("Datový pohled",["Týmy","Rozhodčí"],default="Týmy",label_visibility="collapsed")

    if data_mode=="Týmy":
        H_current=H[H.season.astype(str)==str(season)].copy()
        selected_team=st.selectbox("Tým",sorted(H_current.team.dropna().astype(str).unique()),key="data_team")
        view=st.segmented_control("Zobrazení",["Tabulka","Grafy"],default="Tabulka",key="data_team_view")
        g=H_current[H_current.team.astype(str)==selected_team].sort_values(["match_date","match_id"]).copy()
        g["Datum"]=g.match_date.dt.strftime("%d.%m.%Y")
        g["Zápas"]=g.apply(lambda r: f"{r.team} – {r.opponent}" if r.venue=="H" else f"{r.opponent} – {r.team}",axis=1)
        g["Výsledek"]=g.apply(lambda r: f"{int(r.goals_for)}:{int(r.goals_against)}" if r.venue=="H" else f"{int(r.goals_against)}:{int(r.goals_for)}",axis=1)
        if view=="Tabulka":
            out=pd.DataFrame({
                "Datum":g["Datum"],"Sezóna":g.season,"Zápas":g["Zápas"],"Výsledek":g["Výsledek"],
                "Fauly pro":pd.to_numeric(g.fouls_committed,errors="coerce"),"Fauly proti":pd.to_numeric(g.fouls_suffered,errors="coerce"),
                "Karty pro":pd.to_numeric(g.yellow_cards,errors="coerce"),"Karty proti":pd.to_numeric(g.yellow_cards_opponent,errors="coerce"),
                "Rohy pro":pd.to_numeric(g.corners_for,errors="coerce"),"Rohy proti":pd.to_numeric(g.corners_against,errors="coerce"),
            })
            st.dataframe(out,use_container_width=True,hide_index=True,height=650)
        else:
            chart=g.copy(); chart["Osa"]=chart["Datum"]+" · "+chart.opponent.astype(str)
            st.markdown("#### Fauly")
            paired_bar_chart(chart,"Osa","fouls_committed","fouls_suffered","Pro","Proti")
            st.markdown("#### Karty")
            paired_bar_chart(chart,"Osa","yellow_cards","yellow_cards_opponent","Pro","Proti")
            st.markdown("#### Rohy")
            paired_bar_chart(chart,"Osa","corners_for","corners_against","Pro","Proti")
            st.caption("Zápasy jsou zleva od nejstaršího po nejnovější. Dvě barvy oddělují hodnoty Pro a Proti.")

    else:
        RM=referee_matches()
        RM=RM[RM.season.astype(str)==str(season)].copy() if not RM.empty else RM
        if RM.empty:
            st.info("Nejsou dostupná data rozhodčích.")
        else:
            refs=sorted(RM.referee_key.dropna().astype(str).unique())
            selected_ref=st.selectbox("Rozhodčí",refs,format_func=lambda x: referee_display(x,REF_IMPACTS),key="data_ref")
            imp=REF_IMPACTS.get(selected_ref)
            if imp is not None:
                c1,c2=st.columns(2)
                c1.metric("Dopad na fauly",f"{float(imp['fouls_impact']):+.1f}".replace('.',','))
                c2.metric("Dopad na karty",f"{float(imp['cards_impact']):+.1f}".replace('.',','))
                detail=pd.DataFrame(imp.get("season_detail",[]))
                if len(detail):
                    detail=detail.sort_values("season")
                    dd=pd.DataFrame({
                        "Sezóna":detail.season,"Zápasů":detail.matches,
                        "Fauly rozhodčí Ø":detail.fouls_avg.round(2),"Liga Ø":detail.league_fouls_avg.round(2),"Rozdíl fauly":detail.fouls_delta.round(2),
                        "Karty rozhodčí Ø":detail.cards_avg.round(2),"Liga karty Ø":detail.league_cards_avg.round(2),"Rozdíl karty":detail.cards_delta.round(2),
                    })
                    with st.expander("Výpočet po sezónách"):
                        st.dataframe(dd,use_container_width=True,hide_index=True)
                        st.caption("Celkový dopad používá váhy 50 % aktuální sezóna, 30 % minulá, 20 % předminulá. Pokud sezóna chybí, dostupné váhy se poměrně přepočítají.")

            view=st.segmented_control("Zobrazení",["Tabulka","Grafy"],default="Tabulka",key="data_ref_view")
            g=RM[RM.referee_key==selected_ref].sort_values(["match_date","match_id"]).copy()
            g["Datum"]=g.match_date.dt.strftime("%d.%m.%Y")
            g["Zápas"]=g.home_team.astype(str)+" – "+g.away_team.astype(str)
            # Score is joined from H so referee table includes the result as requested.
            home_rows=H[(H.season.astype(str)==str(season))&(H.venue=="H")][["match_id","goals_for","goals_against"]].drop_duplicates("match_id")
            g=g.merge(home_rows,on="match_id",how="left")
            g["Výsledek"]=g.apply(lambda r: f"{int(r.goals_for)}:{int(r.goals_against)}" if pd.notna(r.goals_for) and pd.notna(r.goals_against) else "—",axis=1)
            if view=="Tabulka":
                out=pd.DataFrame({
                    "Datum":g["Datum"],"Sezóna":g.season,"Zápas":g["Zápas"],"Výsledek":g["Výsledek"],
                    "Fauly domácí":pd.to_numeric(g.home_fouls,errors="coerce"),"Fauly hosté":pd.to_numeric(g.away_fouls,errors="coerce"),
                    "Karty domácí":pd.to_numeric(g.home_yellow,errors="coerce"),"Karty hosté":pd.to_numeric(g.away_yellow,errors="coerce"),
                })
                # Corners live in the two team rows; join them for the same match-level logic.
                corners=H[H.season.astype(str)==str(season)].pivot_table(index="match_id",columns="venue",values="corners_for",aggfunc="first").rename(columns={"H":"Rohy domácí","A":"Rohy hosté"}).reset_index()
                out=out.join(g[["match_id"]].reset_index(drop=True)).merge(corners,on="match_id",how="left").drop(columns="match_id")
                st.dataframe(out,use_container_width=True,hide_index=True,height=650)
            else:
                corners=H[H.season.astype(str)==str(season)].pivot_table(index="match_id",columns="venue",values="corners_for",aggfunc="first")
                g=g.join(corners,on="match_id",rsuffix="_corner")
                g["Osa"]=g["Datum"]+" · "+g.home_team.astype(str)+"–"+g.away_team.astype(str)
                st.markdown("#### Fauly")
                paired_bar_chart(g,"Osa","home_fouls","away_fouls","Domácí","Hosté")
                st.markdown("#### Karty")
                paired_bar_chart(g,"Osa","home_yellow","away_yellow","Domácí","Hosté")
                if "H" in g.columns and "A" in g.columns:
                    st.markdown("#### Rohy")
                    paired_bar_chart(g,"Osa","H","A","Domácí","Hosté")
                st.caption("Zápasy jsou zleva od nejstaršího po nejnovější.")

st.caption("Fair kurz = modelový kurz, nikoli aktuální nabídka bookmakera. Bookmaker value scanner bude další vrstva.")
