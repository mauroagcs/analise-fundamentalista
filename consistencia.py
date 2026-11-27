"""Consistência ao longo dos anos (histórico CVM): separa empresa boa de empresa que teve um ano bom.

Cinco testes simples sobre até 10 exercícios anuais. Os limites são regras de bolso (como no Filtro Sócio):
ajuste as constantes abaixo se quiser ser mais rígido ou mais flexível.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import cvm
import db
import fundamentus

MIN_ANOS = 8            # histórico mínimo para julgar lucro e crescimento
ROE_ALVO = 15.0         # mesmo corte do Filtro Sócio
DIV_EBITDA_MAX = 3.0    # mesmo corte do Filtro Sócio
JANELA = 5              # "últimos N anos" para ROE, dívida e caixa
EXIGE = 4               # em quantos dos últimos JANELA anos o teste precisa passar
SELO_MINIMO = 4         # selo mínimo para a opção "exigir consistência"

# (nome curto, descrição para a tela)
CRITERIOS = [
    ("Lucro quase sempre", f"Lucro positivo em todos os anos, com no máximo 1 de prejuízo (mínimo {MIN_ANOS} anos de histórico)."),
    ("Lucro crescente", "A mediana do lucro dos 3 últimos anos é maior que a dos 3 primeiros."),
    ("ROE alto", f"ROE ≥ {ROE_ALVO:g}% em pelo menos {EXIGE} dos últimos {JANELA} anos."),
    ("Dívida controlada", f"Dív.Líq/EBITDA < {DIV_EBITDA_MAX:g} (ou caixa líquido) em pelo menos {EXIGE} dos últimos {JANELA} anos. Não se aplica a bancos."),
    ("Caixa operacional", f"Caixa gerado pelas operações positivo em pelo menos {EXIGE} dos últimos {JANELA} anos. Não se aplica a bancos."),
]


def _lucro(h: pd.DataFrame) -> pd.Series:
    return h["lucro_ctrl"].fillna(h["lucro"])


def cagr(serie: pd.Series) -> float:
    s = serie.dropna()
    if len(s) < 3 or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return np.nan
    return ((s.iloc[-1] / s.iloc[0]) ** (1 / (len(s) - 1)) - 1) * 100


def avaliar(h: pd.DataFrame, financeira: bool) -> dict:
    """h = cvm.indicadores_anuais(histórico de uma empresa). Cada teste vira (nome, True|False|None, detalhe)."""
    n = len(h)
    lucro = _lucro(h).reset_index(drop=True)
    ult = h.tail(JANELA).reset_index(drop=True)
    pos = int((lucro > 0).sum())
    testes: list[tuple[str, bool | None, str]] = []

    # 1. lucro
    testes.append((CRITERIOS[0][0], (pos >= n - 1) if n >= MIN_ANOS else None, f"lucro em {pos} de {n} anos"))
    # 2. crescimento
    if n >= 6:
        ini, fim = lucro.head(3).median(), lucro.tail(3).median()
        testes.append((CRITERIOS[1][0], bool(fim > ini), f"mediana R$ {fim / 1e9:.2f} bi vs R$ {ini / 1e9:.2f} bi".replace(".", ",")))
    else:
        testes.append((CRITERIOS[1][0], None, "histórico curto"))
    # 3. ROE
    roe = ult["roe"].dropna()
    if len(roe) >= EXIGE:
        k = int((roe >= ROE_ALVO).sum())
        testes.append((CRITERIOS[2][0], k >= EXIGE, f"ROE ≥ {ROE_ALVO:g}% em {k} de {len(roe)} anos"))
    else:
        testes.append((CRITERIOS[2][0], None, "sem dados"))
    # 4 e 5. só para não financeiras
    if financeira:
        testes += [(CRITERIOS[3][0], None, "não se aplica"), (CRITERIOS[4][0], None, "não se aplica")]
    else:
        conhecido = ult["divida_liquida"].notna()
        bom = conhecido & ((ult["divida_liquida"] < 0) | (ult["div_liq_ebitda"] < DIV_EBITDA_MAX))
        if conhecido.sum() >= EXIGE:
            testes.append((CRITERIOS[3][0], int(bom.sum()) >= EXIGE, f"dívida ok em {int(bom.sum())} de {int(conhecido.sum())} anos"))
        else:
            testes.append((CRITERIOS[3][0], None, "sem dados"))
        fco = ult["fco"].dropna()
        if len(fco) >= EXIGE:
            k = int((fco > 0).sum())
            testes.append((CRITERIOS[4][0], k >= EXIGE, f"caixa operacional positivo em {k} de {len(fco)} anos"))
        else:
            testes.append((CRITERIOS[4][0], None, "sem dados"))

    aplicaveis = [t for t in testes if t[1] is not None]
    return {
        "testes": testes,
        "selo_ok": sum(1 for t in aplicaveis if t[1]),
        "selo_n": len(aplicaveis),
        "anos_hist": n,
        "anos_lucro": pos,
        "cagr_lucro": cagr(lucro),
        "roe_min5": float(roe.min()) if len(roe) else np.nan,
    }


def completar_codigos_cvm(tickers: list[str], progresso=None) -> int:
    """Garante o código CVM de cada ticker (necessário para casar com o histórico). Devolve quantos buscou."""
    faltam = [t for t in tickers if db.cd_cvm_do_ticker(t) is None]

    def buscar(t):
        try:
            return t, fundamentus.obter_cd_cvm(t)
        except fundamentus.ErroFundamentus:
            return t, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (t, cd) in enumerate(pool.map(buscar, faltam), 1):
            if cd is not None:
                db.salvar_cd_cvm(t, cd)
            if progresso:
                progresso(i, len(faltam))
    return len(faltam)


CAMPOS = ["anos_hist", "anos_lucro", "cagr_lucro", "roe_min5", "selo_ok", "selo_n"]


def anexar(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as métricas de consistência ao DataFrame de ações (NaN onde não há histórico mapeado)."""
    df = df.copy()
    for c in CAMPOS:
        df[c] = np.nan
    if df.empty or db.meta_get("historico_em") is None:
        return df
    todo, mapa = db.ler_todo_historico(), db.mapa_tickers()
    if todo.empty or not mapa:
        return df
    fin_por_cd = {mapa[t]: bool(f) for t, f in zip(df["ticker"], df["financeira"]) if t in mapa}
    linhas = {}
    for cd, g in todo.groupby("cd_cvm"):
        if cd in fin_por_cd:
            r = avaliar(cvm.indicadores_anuais(g), fin_por_cd[cd])
            linhas[cd] = {c: r[c] for c in CAMPOS}
    if not linhas:
        return df
    tab = pd.DataFrame.from_dict(linhas, orient="index")
    cds = df["ticker"].map(mapa)
    for c in CAMPOS:
        df[c] = cds.map(tab[c])
    return df
