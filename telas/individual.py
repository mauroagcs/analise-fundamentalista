"""Tela 2 — Análise individual de uma ação."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import consistencia
import db
import regras
import resumo
import ui
from regras import INDICADORES, fmt

GRUPOS = ["Valuation", "Rentabilidade", "Margens", "Endividamento", "Liquidez", "Crescimento"]


def _t(v, padrao: str = "n/d") -> str:
    return padrao if pd.isna(v) else str(v)


def _delta(chave: str, valor, mediana) -> tuple[str | None, str]:
    """Texto e cor do st.metric comparando com a mediana do setor."""
    ind = INDICADORES[chave]
    if pd.isna(valor) or pd.isna(mediana) or (ind.so_positivo and valor <= 0) or chave == "liq_2m":
        return None, "off"
    dif = valor - mediana
    sinal = "+" if dif >= 0 else "−"
    unidade = " p.p." if ind.tipo == "pct" else ""
    cor = "off" if ind.melhor is None else ("normal" if ind.melhor == "alto" else "inverse")
    return f"{sinal}{regras._br(abs(dif), 1)}{unidade} vs setor ({fmt(mediana, ind.tipo)})", cor


def _metricas(df: pd.DataFrame, r: pd.Series, chaves: list[str], setor_ok: bool) -> None:
    """Uma linha de st.metric por 3 indicadores, cada um comparado com a mediana do setor."""
    for i in range(0, len(chaves), 3):
        cols = st.columns(3)
        for c, k in zip(cols, chaves[i:i + 3]):
            ind = INDICADORES[k]
            med = regras.mediana_setor(df, r["setor"], k) if setor_ok else np.nan
            txt, cor = _delta(k, r[k], med)
            c.metric(ind.rotulo, fmt(r[k], ind.tipo), delta=txt, delta_color=cor, help=ind.ajuda or None)


def _lista(titulo_ajuda: str, itens: list[str], icone: str) -> None:
    st.caption(titulo_ajuda)
    for i in itens:
        st.markdown(f"{icone} {i}")


def _resumo(df: pd.DataFrame, r: pd.Series, ticker: str) -> None:
    perfil = db.ler_perfil(ticker)

    st.subheader("O que a empresa faz")
    if perfil:
        st.markdown(perfil["o_que_faz"] or "_Sem descrição._")
        if perfil["diferenciais"]:
            st.markdown("**Diferenciais competitivos**")
            for d in perfil["diferenciais"]:
                st.markdown(f"- {d}")
        st.caption(f"🧠 Gerado por IA ({perfil['_modelo']}) em {perfil['_gerado_em'][:10]}, a partir do conhecimento "
                   "geral do modelo — pode estar desatualizado ou impreciso. Confirme no Formulário de Referência "
                   "da empresa (RI/CVM) antes de decidir.")
    else:
        st.info("Descrição e diferenciais não existem nos dados do Fundamentus/CVM. Posso pedir ao Claude um resumo "
                "do negócio; o resultado fica salvo localmente. Só são enviados nome, ticker e setor da empresa.")
    rotulo = "🔁 Gerar de novo" if perfil else "🧠 Gerar resumo com IA"
    if st.button(rotulo, key=f"ia_{ticker}"):
        with st.spinner("Consultando o Claude…"):
            try:
                db.salvar_perfil(ticker, resumo.gerar_perfil_ia(r), resumo.MODELO_IA)
            except resumo.ErroIA as e:
                st.error(str(e))
            else:
                st.rerun()

    fortes, fracos = resumo.pontos_dados(df, r, ui.historico_da_empresa(ticker))
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("✅ Pontos fortes")
        _lista("📊 Pelos números", fortes or ["Nenhum destaque positivo claro nos indicadores."], "🟢")
        if perfil and perfil["pontos_fortes"]:
            _lista("🧠 Pelo negócio (IA)", perfil["pontos_fortes"], "🟢")
    with c2:
        st.subheader("⚠️ Pontos fracos e atenção")
        _lista("📊 Pelos números", fracos or ["Nenhum alerta claro nos indicadores."], "🟠")
        if perfil and perfil["pontos_fracos"]:
            _lista("🧠 Pelo negócio (IA)", perfil["pontos_fracos"], "🟠")
    st.caption("Os pontos 📊 seguem regras fixas (ex.: ROE ≥ 15% é forte, Dív.Líq/EBITDA > 3 é fraco) e comparam com a "
               "mediana do setor quando há amostra. São um ponto de partida, não um veredito.")


def _visao_geral(df: pd.DataFrame, r: pd.Series, setor_ok: bool) -> None:
    crit = regras.criterios_socio(df.loc[[r.name]]).iloc[0]
    st.subheader("Checklist de sócio")
    if r["financeira"]:
        st.caption("Dív.Líq/EBITDA não se aplica a bancos e seguradoras — critério dispensado.")
    cols = st.columns(len(crit))
    for c, (nome, ok) in zip(cols, crit.items()):
        c.markdown(f"{'✅' if ok else '❌'} **{nome}**")
    if crit.all():
        st.success("Passa no **Filtro Sócio** (com os parâmetros padrão).")

    for grupo in GRUPOS:
        chaves = [k for k, i in INDICADORES.items() if i.grupo == grupo]
        st.markdown(f"##### {grupo}")
        _metricas(df, r, chaves, setor_ok)


def _cagr(serie: pd.Series) -> float:
    n = len(serie)
    if n < 3 or serie.iloc[0] <= 0 or serie.iloc[-1] <= 0:
        return np.nan
    return ((serie.iloc[-1] / serie.iloc[0]) ** (1 / (n - 1)) - 1) * 100


def _painel_consistencia(h: pd.DataFrame, financeira: bool) -> None:
    """Os 5 testes de história: o que separa empresa boa de empresa que teve um ano bom."""
    res = consistencia.avaliar(h, financeira)
    st.subheader(f"Selo de consistência: {res['selo_ok']} de {res['selo_n']}")
    cols = st.columns(len(res["testes"]))
    for c, (nome, ok, detalhe), (_, desc) in zip(cols, res["testes"], consistencia.CRITERIOS):
        icone = "➖" if ok is None else ("✅" if ok else "❌")
        c.markdown(f"{icone} **{nome}**")
        c.caption(detalhe, help=desc)
    st.caption("Cada teste olha até 10 anos de balanços. ➖ = não se aplica ou histórico insuficiente.")


def _historico(ticker: str, r: pd.Series) -> None:
    h = ui.historico_da_empresa(ticker)
    if h.empty:
        if db.meta_get("historico_em") is None:
            st.info("O histórico de 10 anos vem dos balanços anuais da CVM (download único de ≈130 MB).")
            if st.button("⬇️ Baixar histórico agora", key="baixar_hist"):
                ui.atualizar_historico()
                st.rerun()
        else:
            st.warning("Não encontrei balanços anuais desta empresa na CVM.")
        return

    lucro = h["lucro_ctrl"].fillna(h["lucro"])
    h = h.assign(lucro_plot=lucro)
    a, b, c = st.columns(3)
    a.metric("Anos com lucro", f"{int((lucro > 0).sum())} de {len(h)}",
             help="Empresa 'comprovada no tempo' lucra na maioria dos anos.")
    periodo = f"{int(h['ano'].iloc[0])}–{int(h['ano'].iloc[-1])}"
    b.metric(f"Crescimento do lucro ({periodo})", f"{fmt(_cagr(lucro), 'pct')} ao ano")
    c.metric(f"Crescimento da receita ({periodo})", f"{fmt(_cagr(h['receita']), 'pct')} ao ano")

    _painel_consistencia(h, bool(r["financeira"]))

    rot_rec = "Receita da intermediação" if r["financeira"] else "Receita"
    g1, g2 = st.columns(2)
    g1.plotly_chart(ui.barras_anuais(h, {rot_rec: "receita"}, "Receita"), width="stretch")
    g2.plotly_chart(ui.barras_anuais(h, {"Lucro líquido": "lucro_plot"}, "Lucro líquido dos controladores"),
                    width="stretch")
    g3, g4 = st.columns(2)
    g3.plotly_chart(ui.linhas_anuais(h, {"ROE": "roe"}, "ROE (%)", "%"), width="stretch")
    g4.plotly_chart(ui.linhas_anuais(h, {"Margem líquida": "mrg_liq"}, "Margem líquida (%)", "%"),
                    width="stretch")

    st.subheader("Caixa, dívida e dividendos")
    if not r["financeira"]:
        e1, e2 = st.columns(2)
        e1.plotly_chart(ui.barras_anuais(h, {"Caixa das operações": "fco", "Lucro líquido": "lucro_plot"},
                                         "O lucro vira caixa?"), width="stretch")
        e2.plotly_chart(ui.barras_anuais(h, {"EBITDA": "ebitda"}, "EBITDA"), width="stretch")
        e3, e4 = st.columns(2)
        e3.plotly_chart(ui.linhas_anuais(h, {"Dív.Líq/EBITDA": "div_liq_ebitda"},
                                         "Dív.Líq/EBITDA (negativo = caixa líquido)", "", 2), width="stretch")
        e4.plotly_chart(ui.barras_anuais(h, {"Caixa livre (FCO − capex)": "fcl"}, "Fluxo de caixa livre"),
                        width="stretch")
    if h["dividendos"].notna().any():
        d1, d2 = st.columns(2)
        d1.plotly_chart(ui.barras_anuais(h, {"Dividendos e JCP pagos": "dividendos"}, "Dividendos e JCP pagos"),
                        width="stretch")
        d2.plotly_chart(ui.linhas_anuais(h, {"Payout": "payout"}, "Payout (% do lucro)", "%"), width="stretch")
    elif r["financeira"]:
        st.caption("Sem série de dividendos nos balanços desta empresa.")
    with st.expander("Ver tabela"):
        t = h[["ano", "receita", "lucro_plot", "patrimonio_ctrl", "mrg_liq", "roe", "ebitda", "fco", "dividendos"]].copy()
        for col in ("receita", "lucro_plot", "patrimonio_ctrl", "ebitda", "fco", "dividendos"):
            t[col] = t[col] / 1e6
        t.columns = ["Ano", "Receita (R$ mi)", "Lucro líquido (R$ mi)", "Patrimônio líq. (R$ mi)",
                     "Margem líq. (%)", "ROE (%)", "EBITDA (R$ mi)", "Caixa operacional (R$ mi)",
                     "Dividendos pagos (R$ mi)"]
        st.dataframe(t.round(1), hide_index=True, width="stretch")
    st.caption("Fonte: DFPs anuais da CVM (consolidado quando disponível). Valores nominais, sem correção pela inflação.")


def _endividamento(ticker: str, df: pd.DataFrame, r: pd.Series, setor_ok: bool) -> None:
    if r["financeira"]:
        st.warning("**Analisar à parte.** Em bancos e seguradoras a dívida faz parte do negócio; "
                   "Dív./EBITDA não se aplica. Olhe capital regulatório, inadimplência e sinistralidade.")
        return
    a, b = st.columns(2)
    a.metric("Dívida bruta", regras.fmt_brl_abrev(r["div_bruta"]))
    b.metric("Dívida líquida", regras.fmt_brl_abrev(r["div_liquida"]),
             help="Negativo = a empresa tem mais caixa do que dívida.")
    _metricas(df, r, ["div_liq_ebitda", "div_bruta_pl", "liq_corr"], setor_ok)

    h = ui.historico_da_empresa(ticker)
    if h.empty:
        st.caption("Baixe o histórico (aba *Histórico*) para ver a evolução da dívida.")
        return
    g1, g2 = st.columns(2)
    g1.plotly_chart(ui.barras_anuais(h, {"Dívida bruta": "divida_bruta", "Caixa e aplicações": "caixa"},
                                     "Dívida bruta vs. caixa"), width="stretch")
    g2.plotly_chart(ui.linhas_anuais(h, {"Dív.Líq/PL": "div_liq_pl"}, "Dívida líquida / patrimônio", "", 2),
                    width="stretch")
    st.caption("Dívida = empréstimos, financiamentos e debêntures (circulante + longo prazo), balanços anuais CVM.")


def _setor(df: pd.DataFrame, r: pd.Series) -> None:
    g = regras.grupo_setor(df, r["setor"])
    st.caption(f"Setor **{r['setor']}** — {len(g)} ações líquidas na base (mediana só é calculada com 3 ou mais).")
    linhas = []
    for k, ind in INDICADORES.items():
        if k == "liq_2m":
            continue
        linhas.append({"Indicador": ind.rotulo, "Esta ação": r[k],
                       "Mediana do setor": regras.mediana_setor(df, r["setor"], k),
                       "Supera % do setor": regras.percentil_no_setor(df, r["setor"], k, r[k])})
    tab = pd.DataFrame(linhas)
    st.dataframe(tab, hide_index=True, width="stretch", height=35 * len(tab) + 38, column_config={
        "Esta ação": st.column_config.NumberColumn(format="%.2f"),
        "Mediana do setor": st.column_config.NumberColumn(format="%.2f"),
        "Supera % do setor": st.column_config.ProgressColumn(
            format="%.0f%%", min_value=0, max_value=100,
            help="Percentual das empresas do setor que ficam atrás desta (considera o que é 'melhor' em cada indicador)."),
    })
    pct = ["roe", "roic", "mrg_liq", "mrg_ebit", "dy", "cresc_rec_5a"]
    ok = [k for k in pct if not pd.isna(r[k])]
    if ok:
        nomes = [INDICADORES[k].rotulo.replace(" (%)", "") for k in ok]
        fig = ui.barras_agrupadas(
            nomes, {r["ticker"]: [r[k] for k in ok],
                    "Mediana do setor": [regras.mediana_setor(df, r["setor"], k) for k in ok]},
            "Rentabilidade e margens (%) vs. mediana do setor", "%",
            cores={r["ticker"]: ui.CORES[0], "Mediana do setor": ui.COR_NEUTRA})
        st.plotly_chart(fig, width="stretch")


def render() -> None:
    st.title("🏢 Análise individual")
    if ui.sem_dados():
        return
    df = ui.dados()
    tickers = sorted(df["ticker"])
    atual = st.session_state.get("ticker_atual", "WEGE3")
    ticker = st.selectbox("Ação", tickers, index=tickers.index(atual) if atual in tickers else 0,
                          format_func=ui.rotulo_ticker(df), help="Digite para buscar.")
    st.session_state["ticker_atual"] = ticker
    r = df[df["ticker"] == ticker].iloc[0]
    setor_ok = isinstance(r["setor"], str)

    topo, fav = st.columns([5, 1])
    topo.subheader(_t(r["empresa"], ticker))
    topo.caption(f"{_t(r['tipo'], '')} · {_t(r['setor'])} › {_t(r['subsetor'])} · "
                 f"último balanço: {_t(r['ult_balanco'])}")
    eh_fav = ticker in set(db.ler_favoritas()["ticker"])
    if fav.button("★ Nas favoritas" if eh_fav else "☆ Favoritar", width="stretch"):
        (db.desfavoritar if eh_fav else db.favoritar)(ticker)
        st.rerun()

    if r["financeira"]:
        st.warning("🏦 **Banco/seguradora — analisar à parte.** Dív./EBITDA e indicadores de dívida "
                   "não se aplicam; foque em ROE, P/VP, dividendos e qualidade da carteira.")

    m = st.columns(5)
    m[0].metric("Cotação", fmt(r["cotacao"], "preco"))
    m[1].metric("Valor de mercado", regras.fmt_brl_abrev(r["valor_mercado"]))
    m[2].metric("Lucro 12m", regras.fmt_brl_abrev(r["lucro_12m"]))
    m[3].metric("Receita 12m", regras.fmt_brl_abrev(r["receita_12m"]))
    m[4].metric("Patrimônio líquido", regras.fmt_brl_abrev(r["patrimonio"]))

    t0, t1, t2, t3, t4 = st.tabs(["🧭 Resumo", "📋 Indicadores", "📈 Histórico (10 anos)",
                                  "🏦 Endividamento", "🏭 vs. setor"])
    with t0:
        _resumo(df, r, ticker)
    with t1:
        _visao_geral(df, r, setor_ok)
    with t2:
        _historico(ticker, r)
    with t3:
        _endividamento(ticker, df, r, setor_ok)
    with t4:
        if setor_ok:
            _setor(df, r)
        else:
            st.info("Setor indisponível: atualize os dados.")
