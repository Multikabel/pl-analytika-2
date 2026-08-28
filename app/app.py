from pathlib import Path
from datetime import date
import os,sys,subprocess
import joblib
import numpy as np
import pandas as pd
import streamlit as st

BASE=Path(__file__).resolve().parent.parent
SCRIPTS=BASE/"scripts"; MODELS=BASE/"models"; TABLES=BASE/"data"/"tables"
sys.path.insert(0,str(SCRIPTS))

from count_common import load_config, ensemble_prediction, over_probability, fair_odds
from fixture_features import build_fixture_rows
from score_round import score_fixtures
from update_fixtures import load_fixtures,current_round,sync_fixtures
from update_officials import sync_officials,referee_for_match,referee_choices
from prediction_archive import load_log, archive_selected_predictions, settle_predictions, summary_stats

st.set_page_config(page_title="PL Analytika 2.0",page_icon="⚽",layout="wide",initial_sidebar_state="collapsed")

MARKETS=("fouls","corners","yellow_cards")
LABEL={"fouls":"Fauly","corners":"Rohy","yellow_cards":"ŽK"}
IS_CLOUD=bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_SERVER_HEADLESS"))

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

@st.cache_resource(show_spinner=False)
def models():
    out={}
    for m in MARKETS:
        p=MODELS/f"{m}_model.joblib"
        if p.exists(): out[m]=joblib.load(p)
    return out

def pct(x): return f"{100*x:.0f}%"
def fmt_odds(x): return f"{x:.2f}" if np.isfinite(x) else "—"

def predict_one(home,away,match_date,season,referee):
    fx=build_fixture_rows(home,away,referee,str(match_date),season)
    rec=[]
    for market,art in models().items():
        cfg=art["config"]
        for c in cfg["features"]:
            if c not in fx: fx[c]=np.nan
        pred,extra,base=ensemble_prediction(art["model"],fx,art["train_mean"],cfg)
        for i,row in fx.iterrows():
            for line in cfg["over_lines"]:
                p=float(over_probability([pred[i]],line,cfg)[0])
                rec.append({
                    "team":row.team,"venue":row.venue,"market":market,"line":line,
                    "prediction":float(pred[i]),"p_over":p,
                    "fair_over":float(fair_odds([p])[0]),
                    "model_component":float(extra[i]),"baseline_component":float(base[i])
                })
    return pd.DataFrame(rec)

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
ref_hist=sorted(H.referee.dropna().unique())

st.title("⚽ PL Analytika 2.0")

nav=st.segmented_control("Pohled",["Kolo","Zápas","Tipy","Týmy"],default="Kolo",label_visibility="collapsed")
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

    score=st.session_state.get("round_score")
    selected_parts=[]
    for _,r in round_df.iterrows():
        ref=referee_for_match(r.home_team,r.away_team,rnd)
        status="✅ Odehráno" if r.played else "🕒 Čeká"
        st.markdown(
            f'<div class="match-card"><b>{r.home_team} – {r.away_team}</b><br>'
            f'<span class="muted">{pd.to_datetime(r.match_date).strftime("%d.%m. %Y")} · '
            f'{r.kickoff_time if pd.notna(r.kickoff_time) and r.kickoff_time else ""} · {status}<br>'
            f'👨‍⚖️ {ref or "Rozhodčí zatím neurčen"}</span></div>',
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
    # Try to infer round and referee from current schedule.
    try:
        sch=load_fixtures(ss,auto_sync=False)
        q=sch[(sch.home_team==home)&(sch.away_team==away)&(sch.match_date==str(md))]
        if len(q):
            rr=int(q.iloc[0].match_round)
            try: sync_officials(rr)
            except Exception: pass
            auto_ref=referee_for_match(home,away,rr)
    except Exception:
        pass

    choices=referee_choices(ref_hist,auto_ref)
    if auto_ref:
        ref=st.selectbox("Rozhodčí",choices,index=choices.index(auto_ref),
                         help="Automaticky načtený z delegace. Můžeš ho ručně změnit.")
        st.caption("✓ Rozhodčí doplněn automaticky")
    else:
        opts=["— zatím neurčen —"]+choices
        selected=st.selectbox("Rozhodčí",opts,index=0)
        ref="" if selected.startswith("—") else selected
        st.caption("Delegace zatím nebyla nalezena. Model použije neutrální doplnění chybějících referee metrik.")

    if st.button("Spočítat zápas",type="primary",use_container_width=True):
        with st.spinner("Počítám…"):
            st.session_state.single=predict_one(home,away,md,ss,ref)

    scored=st.session_state.get("single")
    if isinstance(scored,pd.DataFrame) and len(scored):
        # compact top-line
        preds=scored.groupby(["team","market"],as_index=False).prediction.first()
        for team in [home,away]:
            tx=preds[preds.team==team].set_index("market")
            cols=st.columns(3)
            for j,m in enumerate(MARKETS):
                val=tx.loc[m,"prediction"] if m in tx.index else np.nan
                cols[j].metric(f"{team} · {LABEL[m]}",f"{val:.2f}")
        st.subheader("Kandidáti s fair kurzem 2,00+")
        display_tip_table(best_high_odds_lines(scored,min_fair))

        with st.expander("Všechny hranice"):
            out=scored.copy()
            out["Trh"]=out.market.map(LABEL)
            out["Tip"]="O"+out.line.astype(str)
            out["P"]=out.p_over.map(pct)
            out["Fair"]=out.fair_over.round(2)
            st.dataframe(out[["team","Trh","Tip","prediction","P","Fair"]],
                         use_container_width=True,hide_index=True)

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
            stake=pd.to_numeric(g.stake_units,errors="coerce").fillna(1.0)
            profit=pd.to_numeric(g.profit_units,errors="coerce").fillna(0)
            total_stake=float(stake.sum())
            total_profit=float(profit.sum())
            by_market.append({
                "Trh":LABEL.get(market,market),
                "Tipů":len(g),
                "Výher":int(wins),
                "Úspěšnost":f"{100*wins/len(g):.1f}%",
                "Prům. kurz":round(pd.to_numeric(g.bookmaker_odds,errors="coerce").mean(),2),
                "Zisk":round(total_profit,2),
                "ROI":f"{100*total_profit/total_stake:+.1f}%" if total_stake else "—",
            })
        st.dataframe(pd.DataFrame(by_market),use_container_width=True,hide_index=True)

        st.subheader("Historie")
        h=settled.sort_values(["match_date","created_at"],ascending=False).copy()
        h["Zápas"]=h.home_team+" – "+h.away_team
        h["Tip"]=h.team+" O"+h.line.astype(str)+" "+h.market.map(LABEL)
        h["Fair"]=pd.to_numeric(h.fair_over,errors="coerce").round(2)
        h["Kurz"]=pd.to_numeric(h.bookmaker_odds,errors="coerce").round(2)
        h["P"]=pd.to_numeric(h.p_over,errors="coerce").map(lambda x:f"{100*x:.0f}%")
        h["Skutečnost"]=pd.to_numeric(h.actual_value,errors="coerce")
        h["Zisk"]=pd.to_numeric(h.profit_units,errors="coerce").map(lambda x:f"{x:+.2f} u" if pd.notna(x) else "—")
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
            p["Kurz"]=pd.to_numeric(p.bookmaker_odds,errors="coerce").round(2)
            st.dataframe(
                p[["match_date","Zápas","Tip","P","Fair","Kurz"]],
                use_container_width=True,hide_index=True
            )

    st.caption("Statistika obsahuje pouze ručně vybrané a uložené tipy. Změna filtru ani nové přepočítání kola nic nepřidá. Po zápase se původní snapshot pouze vyhodnotí WIN/LOSS.")

else:
    st.subheader("Týmy")
    cur=H[H.season==season]
    agg=cur.groupby("team").agg(
        Z=("match_id","count"),Body=("points","sum"),
        Fauly=("fouls_committed","mean"),Fauly_proti=("fouls_suffered","mean"),
        Rohy=("corners_for","mean"),Rohy_proti=("corners_against","mean"),
        ŽK=("yellow_cards","mean"),Střely=("shots_for","mean")
    ).reset_index().rename(columns={"team":"Tým"})
    for c in ["Fauly","Fauly_proti","Rohy","Rohy_proti","ŽK","Střely"]:agg[c]=agg[c].round(2)
    st.dataframe(agg.sort_values("Body",ascending=False),use_container_width=True,hide_index=True,height=700)

st.caption("Fair kurz = modelový kurz, nikoli aktuální nabídka bookmakera. Bookmaker value scanner bude další vrstva.")
