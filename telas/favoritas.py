"""Tela 4 — Favoritas agrupadas por setor, com notas pessoais."""
from __future__ import annotations

import streamlit as st

import db
import regras
import ui
from regras import fmt


def _cartao(r, nota: str, passa: bool) -> None:
    t = r["ticker"]
    c = st.columns([2.2, 1.3, 1, 1, 1, 1.3])
    c[0].markdown(f"**{t}** · {r['empresa'] if isinstance(r['empresa'], str) else ''}  \n"
                  f"{'✅ Filtro Sócio' if passa else '▫️ fora do Filtro Sócio'}"
                  f"{' · 🏦 analisar à parte' if r['financeira'] else ''}")
    c[1].metric("Cotação", fmt(r["cotacao"], "preco"))
    c[2].metric("P/L", fmt(r["pl"], "x"))
    c[3].metric("ROE", fmt(r["roe"], "pct"))
    c[4].metric("Div. Yield", fmt(r["dy"], "pct"))
    c[5].metric("Dív.Líq/EBITDA", "n/a" if r["financeira"] else fmt(r["div_liq_ebitda"], "x"))

    texto = st.text_area("Notas pessoais", value=nota, key=f"nota_{t}", height=90,
                         placeholder="Por que quero ser sócio? O que vigiar? Preço-alvo?",
                         label_visibility="collapsed")
    b = st.columns([1, 1, 1, 4])
    if b[0].button("💾 Salvar nota", key=f"salvar_{t}", disabled=texto == nota):
        db.salvar_nota(t, texto)
        st.toast(f"Nota de {t} salva.")
        st.rerun()
    if b[1].button("🏢 Analisar", key=f"ana_{t}"):
        ui.ir_para_analise(t)
    if b[2].button("🗑️ Remover", key=f"rem_{t}"):
        db.desfavoritar(t)
        st.rerun()


def render() -> None:
    st.title("⭐ Favoritas")
    if ui.sem_dados():
        return
    df = ui.dados()
    favs = db.ler_favoritas()

    with st.form("nova_favorita", clear_on_submit=True):
        a, b = st.columns([3, 1])
        novo = a.selectbox("Adicionar ação", [""] + sorted(df["ticker"]), format_func=lambda t: ui.rotulo_ticker(df)(t) if t else "Escolha ou digite um ticker…",
                           label_visibility="collapsed")
        if b.form_submit_button("➕ Adicionar", width="stretch") and novo:
            db.favoritar(novo)
            st.rerun()

    if favs.empty:
        st.info("Nenhuma favorita ainda. Adicione acima, ou use o botão ☆ na análise individual / no screener.")
        return

    notas = favs.set_index("ticker")["nota"].to_dict()
    sub = df[df["ticker"].isin(notas)].copy()
    passa = regras.passa_filtro_socio(sub)
    sub["_passa"] = passa
    sub["_setor"] = sub["setor"].fillna("Setor não identificado")
    sumidas = sorted(set(notas) - set(sub["ticker"]))

    st.caption(f"{len(sub)} favorita(s) em {sub['_setor'].nunique()} setor(es) · "
               f"{int(passa.sum())} passam no Filtro Sócio.")
    for setor, grupo in sub.sort_values("ticker").groupby("_setor"):
        with st.expander(f"🏭 {setor} ({len(grupo)})", expanded=True):
            for _, r in grupo.iterrows():
                _cartao(r, notas[r["ticker"]], bool(r["_passa"]))
                st.divider()
    if sumidas:  # ticker que saiu do Fundamentus (deslistada, sem liquidez…): mantém a nota acessível
        with st.expander(f"❓ Sem cotação atual ({len(sumidas)})"):
            for t in sumidas:
                st.markdown(f"**{t}** — {notas[t] or '*sem nota*'}")
                if st.button("🗑️ Remover", key=f"rem_{t}"):
                    db.desfavoritar(t)
                    st.rerun()
