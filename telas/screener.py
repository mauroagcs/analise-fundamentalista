"""Tela 1 — Screener: tabela filtrável com preset 'Filtro Sócio'."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import regras
import ui
from regras import INDICADORES

# Colunas da tabela, na ordem de exibição: (coluna, rótulo, formato)
COLUNAS = [
    ("cotacao", "Cotação (R$)", "%.2f"), ("pl", "P/L", "%.1f"), ("pvp", "P/VP", "%.2f"),
    ("dy", "Div. Yield (%)", "%.1f"), ("roe", "ROE (%)", "%.1f"), ("roic", "ROIC (%)", "%.1f"),
    ("mrg_liq", "Mrg. Líq. (%)", "%.1f"), ("mrg_ebit", "Mrg. EBIT (%)", "%.1f"),
    ("div_liq_ebitda", "Dív.Líq/EBITDA", "%.2f"), ("div_bruta_pl", "Dív.Bruta/PL", "%.2f"),
    ("liq_corr", "Liq. Corrente", "%.2f"), ("liq_mi", "Liquidez (R$ mi/dia)", "%.1f"),
    ("cresc_rec_5a", "Cresc. Rec. 5a (%)", "%.1f"),
    # Consistência (histórico CVM de até 10 anos): vazias até baixar o histórico
    ("selo_ok", "Consistência (0–5)", "%.0f"), ("anos_lucro", "Anos c/ lucro", "%.0f"),
    ("cagr_lucro", "Cresc. lucro (% a.a.)", "%.1f"), ("roe_min5", "ROE mín. 5a (%)", "%.1f"),
]
# Indicadores com faixa mín/máx (liquidez é filtrada à parte).
FAIXAS = ["pl", "pvp", "dy", "roe", "roic", "mrg_liq", "mrg_ebit", "div_liq_ebitda",
          "div_bruta_pl", "liq_corr", "cresc_rec_5a", "psr", "ev_ebitda"]


def _faixas(df: pd.DataFrame) -> pd.Series:
    """Desenha os campos mín/máx e devolve a máscara resultante."""
    mask = pd.Series(True, index=df.index)
    cols = st.columns(3)
    for i, k in enumerate(FAIXAS):
        ind = INDICADORES[k]
        with cols[i % 3]:
            st.caption(ind.rotulo, help=ind.ajuda or None)
            a, b = st.columns(2)
            passo = 0.5 if ind.tipo == "x" else 1.0
            mn = a.number_input("mín", value=None, step=passo, placeholder="mín",
                                key=f"min_{k}", label_visibility="collapsed")
            mx = b.number_input("máx", value=None, step=passo, placeholder="máx",
                                key=f"max_{k}", label_visibility="collapsed")
            if mn is not None:
                mask &= df[k] >= mn
            if mx is not None:
                mask &= df[k] <= mx
    return mask


def render() -> None:
    st.title("🔎 Screener")
    if ui.sem_dados():
        return
    df = ui.dados().copy()
    df["liq_mi"] = df["liq_2m"] / 1e6
    favs = set(db.ler_favoritas()["ticker"])

    # --- linha principal de filtros
    c1, c2, c3 = st.columns([1.3, 2, 3])
    socio = c1.toggle("🤝 Filtro Sócio", help="Pré-seleciona empresas com cara de sociedade de longo prazo.")
    busca = c2.text_input("Buscar", placeholder="ticker ou nome da empresa", label_visibility="collapsed")
    setores = sorted(df["setor"].dropna().unique())
    setores_sel = c3.multiselect("Setor", setores, placeholder="Todos os setores",
                                 label_visibility="collapsed")

    mask = pd.Series(True, index=df.index)

    if socio:
        with st.expander("Critérios do Filtro Sócio (ajustáveis)", expanded=False):
            a, b, c, d, e = st.columns(5)
            p = regras.ParametrosSocio(
                consistencia_min=int(e.number_input(
                    "Exigir consistência (selo ≥)", value=0, min_value=0, max_value=5, step=1,
                    help="0 = não exige. O selo conta quantos dos 5 testes de história a empresa passa "
                         "(lucro, crescimento, ROE, dívida, caixa). Precisa do histórico CVM.")),
                liq_min=a.number_input("Liquidez mínima (R$/dia)", value=1_000_000.0, step=250_000.0, min_value=0.0),
                roe_min=b.number_input("ROE mínimo (%)", value=15.0, step=1.0),
                roe_min_utilities=c.number_input("ROE mín. utilities (%)", value=10.0, step=1.0,
                                                 help="Energia elétrica, saneamento e gás."),
                div_liq_ebitda_max=d.number_input("Dív.Líq/EBITDA máx.", value=3.0, step=0.5),
            )
        st.caption(f"Só ações **ON (final 3)** · liquidez ≥ {regras.fmt_brl_abrev(p.liq_min)}/dia · "
                   f"ROE > {p.roe_min:g}% ({p.roe_min_utilities:g}% em utilities) · margem líquida > 0 (bancos: lucro > 0) · "
                   f"Dív.Líq/EBITDA < {p.div_liq_ebitda_max:g}. "
                   "Bancos e seguradoras: sem Dív./EBITDA, marcados *Analisar à parte*."
                   + (f" Consistência: selo ≥ {p.consistencia_min}." if p.consistencia_min else ""))
        mask &= regras.passa_filtro_socio(df, p)

    with st.expander("Filtros por indicador (faixas mín/máx)"):
        l1, l2 = st.columns([1, 3])
        liq_min = l1.number_input("Liquidez mínima (R$/dia)", value=0.0, step=100_000.0, min_value=0.0)
        l2.caption("Deixe em branco para não limitar. Ações sem o dado são excluídas quando há limite.")
        on_only = l1.checkbox("Somente ON (final 3)")
        h1, h2, h3 = st.columns(3)
        h1.caption("Consistência (histórico CVM)", help="Selo de 0 a 5: quantos testes de história a empresa passa.")
        selo_min = h2.number_input("Selo mínimo", value=None, min_value=0, max_value=5, step=1, placeholder="selo ≥")
        lucro_min = h3.number_input("Anos com lucro (mín.)", value=None, min_value=0, max_value=10, step=1,
                                    placeholder="anos ≥")
        mask &= _faixas(df)
        if selo_min is not None:
            mask &= df["selo_ok"] >= selo_min
        if lucro_min is not None:
            mask &= df["anos_lucro"] >= lucro_min
    if liq_min:
        mask &= df["liq_2m"] >= liq_min
    if on_only:
        mask &= df["ticker"].str.fullmatch(r"[A-Z]{4}3")
    if setores_sel:
        mask &= df["setor"].isin(setores_sel)
    if busca:
        b = busca.strip()
        mask &= (df["ticker"].str.contains(b, case=False, regex=False)
                 | df["empresa"].fillna("").str.contains(b, case=False, regex=False))

    res = df[mask].sort_values("liq_2m", ascending=False).reset_index(drop=True)
    st.markdown(f"**{len(res)}** de {len(df)} ações")

    tabela = pd.DataFrame({
        "⭐": res["ticker"].isin(favs).map({True: "⭐", False: ""}),
        "Ticker": res["ticker"],
        "Empresa": res["empresa"],
        "Setor": res["setor"],
        **{rot: res[col] for col, rot, _ in COLUNAS},
        "Aviso": res["aviso"],
    })
    # Styler: mostra "—" onde falta o dado (o padrão do Streamlit exibiria "None") sem perder a ordenação numérica.
    formatos = {rot: "{:,.%sf}" % fmt[2] for _, rot, fmt in COLUNAS}
    estilizada = tabela.style.format(formatos, na_rep="—")
    evento = st.dataframe(estilizada, hide_index=True, width="stretch", height=520,
                          column_config={"⭐": st.column_config.TextColumn("⭐", width="small")},
                          on_select="rerun", selection_mode="multi-row", key="tabela_screener")

    sel = res.iloc[evento.selection.rows]["ticker"].tolist() if evento.selection.rows else []
    b1, b2, b3, b4 = st.columns([1.3, 1.5, 1.5, 3])
    b1.download_button("⬇️ CSV", tabela.to_csv(index=False, sep=";", decimal=","),
                       "screener.csv", "text/csv", disabled=res.empty)
    if sel:
        if b2.button(f"🏢 Analisar {sel[0]}", width="stretch"):
            ui.ir_para_analise(sel[0])
        if b3.button(f"⭐ Favoritar ({len(sel)})", width="stretch"):
            for t in sel:
                db.favoritar(t)
            st.rerun()
        if 2 <= len(sel) <= 5 and b4.button(f"⚖️ Comparar {len(sel)} ações"):
            st.session_state["comparar"] = sel
            st.switch_page(ui.PAGINAS["comparador"])
        elif len(sel) > 5:
            b4.caption("O comparador aceita até 5 ações.")
    else:
        b2.caption("Selecione linhas (caixa à esquerda) para analisar, favoritar ou comparar.")
