"""Tela 3 — Comparador lado a lado (2 a 5 ações)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import regras
import ui
from regras import INDICADORES, fmt

GRAFICOS = {
    "📈 Rentabilidade e margens": ["roe", "roic", "mrg_liq", "mrg_ebit"],
    "💰 Valuation e dividendos": ["pl", "pvp", "dy", "ev_ebitda"],
    "🏦 Endividamento e liquidez": ["div_liq_ebitda", "div_bruta_pl", "liq_corr", "cresc_rec_5a"],
}


def _melhores(num: pd.DataFrame) -> pd.DataFrame:
    """Matriz de estilos CSS: destaca, em cada linha (indicador), a melhor ação."""
    css = pd.DataFrame("", index=num.index, columns=num.columns)
    for k in num.index:
        ind = INDICADORES.get(k)
        if ind is None or ind.melhor is None:
            continue
        v = pd.to_numeric(num.loc[k], errors="coerce")
        if ind.so_positivo:
            v = v.where(v > 0)
        if v.notna().sum() < 2:
            continue
        melhor = v.idxmax() if ind.melhor == "alto" else v.idxmin()
        css.loc[k, melhor] = "background-color: rgba(27,175,122,.22); font-weight: 600"
    return css


def _tabela(sub: pd.DataFrame) -> None:
    chaves = list(INDICADORES)
    num = sub.set_index("ticker")[chaves].T
    txt = pd.DataFrame({t: [fmt(num.loc[k, t], INDICADORES[k].tipo) for k in chaves] for t in num.columns},
                       index=chaves)
    cabecalho = pd.DataFrame(
        {t: [fmt(sub.set_index("ticker").loc[t, "cotacao"], "preco"),
             regras.fmt_brl_abrev(sub.set_index("ticker").loc[t, "valor_mercado"]),
             str(sub.set_index("ticker").loc[t, "setor"]),
             "Analisar à parte" if sub.set_index("ticker").loc[t, "financeira"] else ""] for t in num.columns},
        index=["Cotação", "Valor de mercado", "Setor", "Aviso"])
    estilo = pd.concat([pd.DataFrame("", index=cabecalho.index, columns=num.columns), _melhores(num)])
    tudo = pd.concat([cabecalho, txt])
    tudo.index = estilo.index = list(cabecalho.index) + [INDICADORES[k].rotulo for k in chaves]
    tudo = tudo.reset_index(names="Indicador")  # coluna normal (o índice do Streamlit corta rótulos longos)
    estilo = estilo.reset_index(drop=True)
    estilo.insert(0, "Indicador", "font-weight: 500")
    st.dataframe(tudo.style.apply(lambda _: estilo, axis=None), hide_index=True, width="stretch",
                 height=35 * len(tudo) + 38, column_config={"Indicador": st.column_config.TextColumn(width="medium")})
    st.caption("Verde = melhor valor da linha. P/L, P/VP etc. negativos (prejuízo) não entram na disputa; "
               "bancos/seguradoras não têm indicadores de dívida.")


def render() -> None:
    st.title("⚖️ Comparador")
    if ui.sem_dados():
        return
    df = ui.dados()
    tickers = sorted(df["ticker"])
    atuais = [t for t in st.session_state.get("comparar", []) if t in tickers]
    sel = st.multiselect("Escolha de 2 a 5 ações", tickers, default=atuais, max_selections=5,
                         format_func=ui.rotulo_ticker(df), placeholder="Digite um ticker…")
    st.session_state["comparar"] = sel
    if len(sel) < 2:
        st.info("Selecione pelo menos 2 ações para comparar.")
        return

    sub = df[df["ticker"].isin(sel)].set_index("ticker").loc[sel].reset_index()
    cores = {t: ui.CORES[i] for i, t in enumerate(sel)}
    _tabela(sub)

    abas = st.tabs(list(GRAFICOS) + ["🕰️ Histórico"])
    for aba, (nome, chaves) in zip(abas, GRAFICOS.items()):
        with aba:
            cols = st.columns(2)
            for i, k in enumerate(chaves):
                ind = INDICADORES[k]
                vals = [sub.loc[sub["ticker"] == t, k].iloc[0] for t in sel]
                suf = "%" if ind.tipo == "pct" else ""
                cols[i % 2].plotly_chart(ui.barras_por_entidade(sel, vals, ind.rotulo, cores, suf),
                                         width="stretch")
    with abas[-1]:
        hist = {t: ui.historico_da_empresa(t) for t in sel}
        hist = {t: h for t, h in hist.items() if not h.empty}
        if not hist:
            st.info("Sem histórico. Baixe-o em **Histórico de 10 anos (CVM)**, na barra lateral.")
            return
        for t, h in hist.items():  # receita indexada: 100 = primeiro ano disponível
            if h["receita"].iloc[0] > 0:
                h["receita_idx"] = h["receita"] / h["receita"].iloc[0] * 100
        cols = st.columns(2)
        graficos = [("roe", "ROE (%)", "%"), ("mrg_liq", "Margem líquida (%)", "%"),
                    ("receita_idx", "Receita (base 100 no 1º ano)", ""), ("div_liq_pl", "Dívida líquida / PL", "")]
        for i, (col, titulo, suf) in enumerate(graficos):
            validas = {t: h for t, h in hist.items() if col in h and h[col].notna().any()}
            if validas:
                cols[i % 2].plotly_chart(ui.linhas_por_entidade(validas, col, titulo, cores, suf, 1),
                                         width="stretch")
        faltam = [t for t in sel if t not in hist]
        if faltam:
            st.caption(f"Sem histórico CVM para: {', '.join(faltam)}.")
