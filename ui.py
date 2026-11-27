"""Peças compartilhadas pelas telas: dados em cache, atualização, seleção de ação e gráficos."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import consistencia
import cvm
import db
import fundamentus
import regras

# Paleta categórica validada (slots 1-5, ordem fixa).
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
COR_NEUTRA = "#8a8a85"
DIAS_DETALHES = 15  # re-baixa setor/dívida/EBIT depois disso (balanços saem a cada trimestre)

PAGINAS: dict = {}  # preenchido pelo app.py: nome -> st.Page


# ------------------------------------------------------------------ dados
@st.cache_data(show_spinner=False)
def _carregar(_versao: str) -> pd.DataFrame:
    return consistencia.anexar(regras.preparar(db.ler_tudo()))


def dados() -> pd.DataFrame:
    """Tabela completa (indicadores + setor + derivados + consistência). Vazia se nunca atualizou."""
    return _carregar(f"{db.meta_get('indicadores_em')}|{db.meta_get('detalhes_em')}|"
                     f"{db.meta_get('historico_em')}|{len(db.mapa_tickers())}")


def atualizar_dados(forcar_detalhes: bool = False) -> None:
    """Baixa resultado.php e (quando necessário) detalhes.php de cada ação."""
    with st.status("Atualizando dados do Fundamentus…", expanded=True) as status:
        st.write("Baixando indicadores de todas as ações…")
        df = fundamentus.baixar_resultado()
        db.salvar_indicadores(df)

        tickers = df["ticker"].tolist()
        pendentes = tickers if forcar_detalhes else db.detalhes_desatualizados(tickers, DIAS_DETALHES)
        falhas: list[str] = []
        if pendentes:
            st.write(f"Baixando setor e dívida de {len(pendentes)} ações…")
            barra = st.progress(0.0)
            registros, falhas = fundamentus.baixar_detalhes_em_lote(
                pendentes, lambda i, n: barra.progress(i / n))
            db.salvar_detalhes(registros)
        _carregar.clear()
        msg = f"{len(df)} ações atualizadas."
        if falhas:
            msg += f" {len(falhas)} sem detalhes (tente de novo): {', '.join(falhas[:8])}…"
        status.update(label=msg, state="complete", expanded=False)


def atualizar_historico() -> None:
    with st.status("Baixando balanços anuais da CVM (≈130 MB)…", expanded=True) as status:
        barra = st.progress(0.0)
        h = cvm.baixar_historico(lambda i, n, ano: (barra.progress(min(i / n, 1.0)),
                                                    st.write(f"Exercício {ano} ✔")))
        db.salvar_historico(h)
        st.write("Relacionando cada ação à sua empresa na CVM…")
        barra2 = st.progress(0.0)
        tickers = db.ler_tudo()["ticker"].tolist() if db.meta_get("indicadores_em") else []
        consistencia.completar_codigos_cvm(tickers, lambda i, n: barra2.progress(i / max(n, 1)))
        _carregar.clear()
        status.update(label=f"Histórico de {h['cd_cvm'].nunique()} empresas salvo.",
                      state="complete", expanded=False)


def quando(chave: str) -> str | None:
    v = db.meta_get(chave)
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    dias = (datetime.now() - dt).days
    idade = "hoje" if dias == 0 else f"há {dias} dia{'s' if dias > 1 else ''}"
    return f"{dt:%d/%m/%Y %H:%M} ({idade})"


def historico_da_empresa(ticker: str) -> pd.DataFrame:
    """Histórico anual da CVM da empresa dona do ticker (vazio se indisponível)."""
    if db.meta_get("historico_em") is None:
        return pd.DataFrame()
    cd = db.cd_cvm_do_ticker(ticker)
    if cd is None:
        try:
            cd = fundamentus.obter_cd_cvm(ticker)
        except fundamentus.ErroFundamentus:
            return pd.DataFrame()
        if cd is None:
            return pd.DataFrame()
        db.salvar_cd_cvm(ticker, cd)
    h = db.ler_historico(cd)
    return cvm.indicadores_anuais(h) if not h.empty else pd.DataFrame()


# ------------------------------------------------------------------ navegação / estado
def ir_para_analise(ticker: str) -> None:
    st.session_state["ticker_atual"] = ticker
    st.switch_page(PAGINAS["individual"])


def rotulo_ticker(df: pd.DataFrame):
    nomes = df.set_index("ticker")["empresa"].fillna("").to_dict()
    return lambda t: f"{t} — {nomes.get(t, '')}"


def sem_dados() -> bool:
    """Mostra o aviso de primeira execução. True se não há dados (a tela deve parar)."""
    df = dados()
    if df.empty:
        st.info("Ainda não há dados. Clique em **🔄 Atualizar dados** na barra lateral "
                "(leva cerca de 1 minuto na primeira vez).")
        return True
    if df["setor"].isna().all():
        st.warning("Faltam os setores das ações. Clique em **🔄 Atualizar dados** de novo.")
    return False


# ------------------------------------------------------------------ gráficos
def _base(fig: go.Figure, altura: int = 340) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=8, r=8, t=56, b=8), plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1), hoverlabel=dict(font_size=13),
        font=dict(size=13), bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, linecolor="rgba(128,128,128,.4)", type="category")
    fig.update_yaxes(gridcolor="rgba(128,128,128,.18)", zeroline=True,
                     zerolinecolor="rgba(128,128,128,.5)")
    return fig


def barras_agrupadas(categorias: list[str], series: dict[str, list], titulo: str,
                     sufixo: str = "", casas: int = 1, cores: dict[str, str] | None = None) -> go.Figure:
    """series: nome -> valores (um por categoria). Cor por entidade (cores[nome])."""
    fig = go.Figure()
    for i, (nome, vals) in enumerate(series.items()):
        cor = (cores or {}).get(nome, CORES[i % len(CORES)])
        fig.add_bar(name=nome, x=categorias, y=vals, marker_color=cor,
                    hovertemplate=f"{nome}<br>%{{x}}: %{{y:,.{casas}f}}{sufixo}<extra></extra>")
    fig.update_layout(title=dict(text=titulo, font=dict(size=15)), barmode="group")
    return _base(fig)


def barras_anuais(h: pd.DataFrame, colunas: dict[str, str], titulo: str, escala: float = 1e9,
                  unidade: str = "R$ bi") -> go.Figure:
    """Barras por ano para uma ou mais colunas do histórico (nome exibido -> coluna)."""
    fig = go.Figure()
    for i, (nome, col) in enumerate(colunas.items()):
        fig.add_bar(name=nome, x=h["ano"].astype(int).astype(str), y=h[col] / escala,
                    marker_color=CORES[i],
                    hovertemplate=f"{nome}<br>%{{x}}: {unidade} %{{y:,.2f}}<extra></extra>")
    fig.update_layout(title=dict(text=f"{titulo} ({unidade})", font=dict(size=15)), barmode="group",
                      showlegend=len(colunas) > 1)
    return _base(fig)


def linhas_anuais(h: pd.DataFrame, colunas: dict[str, str], titulo: str, sufixo: str = "",
                  casas: int = 1) -> go.Figure:
    fig = go.Figure()
    for i, (nome, col) in enumerate(colunas.items()):
        fig.add_scatter(name=nome, x=h["ano"].astype(int).astype(str), y=h[col], mode="lines+markers",
                        line=dict(color=CORES[i], width=2), marker=dict(size=8, line=dict(width=2, color="white")),
                        hovertemplate=f"{nome}<br>%{{x}}: %{{y:,.{casas}f}}{sufixo}<extra></extra>")
    fig.update_layout(title=dict(text=titulo, font=dict(size=15)), showlegend=len(colunas) > 1)
    return _base(fig)


def barras_por_entidade(entidades: list[str], valores: list, titulo: str, cores: dict[str, str],
                        sufixo: str = "", casas: int = 1) -> go.Figure:
    """Uma barra por entidade (ação), cor fixa por entidade; valor escrito sobre a barra."""
    fig = go.Figure(go.Bar(
        x=entidades, y=valores, marker_color=[cores[e] for e in entidades],
        text=[("—" if v is None or pd.isna(v) else f"{v:,.{casas}f}{sufixo}") for v in valores],
        textposition="outside", cliponaxis=False,
        hovertemplate=f"%{{x}}: %{{y:,.{casas}f}}{sufixo}<extra></extra>"))
    fig.update_layout(title=dict(text=titulo, font=dict(size=14)), showlegend=False)
    return _base(fig, 280)


def linhas_por_entidade(series: dict[str, pd.DataFrame], coluna: str, titulo: str,
                        cores: dict[str, str], sufixo: str = "", casas: int = 1) -> go.Figure:
    """Uma linha por ação ao longo dos anos (series: ticker -> histórico anual)."""
    fig = go.Figure()
    for nome, h in series.items():
        fig.add_scatter(name=nome, x=h["ano"].astype(int).astype(str), y=h[coluna], mode="lines+markers",
                        line=dict(color=cores[nome], width=2),
                        marker=dict(size=8, line=dict(width=2, color="white")),
                        hovertemplate=f"{nome}<br>%{{x}}: %{{y:,.{casas}f}}{sufixo}<extra></extra>")
    fig.update_layout(title=dict(text=titulo, font=dict(size=14)))
    return _base(fig, 300)
