"""Histórico anual (receita, lucro, PL, dívida) a partir das DFPs abertas da CVM.

O Fundamentus só publica o histórico como imagem; a CVM publica os mesmos balanços
como CSV em dados.cvm.gov.br (uso livre).
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import requests

URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"
ANOS = 10


def _ler(zf: zipfile.ZipFile, demonstracao: str, tipo: str, ano: int) -> pd.DataFrame:
    """Lê um CSV do zip e devolve só o exercício atual, última versão, com valores em R$."""
    nome = f"dfp_cia_aberta_{demonstracao}_{tipo}_{ano}.csv"
    if nome not in zf.namelist():
        return pd.DataFrame()
    d = pd.read_csv(zf.open(nome), sep=";", encoding="latin-1", dtype=str)
    d = d[d["ORDEM_EXERC"].str.startswith("\xdaLT")].copy()  # "ÚLTIMO" (e não "PENÚLTIMO")
    d["cd_cvm"] = d["CD_CVM"].astype(int)
    d["ano"] = d["DT_REFER"].str[:4].astype(int)
    d["valor"] = pd.to_numeric(d["VL_CONTA"], errors="coerce") * d["ESCALA_MOEDA"].map({"MIL": 1000}).fillna(1)
    d["versao"] = d["VERSAO"].astype(int)
    d = d.sort_values("versao").drop_duplicates(["cd_cvm", "ano", "CD_CONTA"], keep="last")
    return d.rename(columns={"CD_CONTA": "conta", "DS_CONTA": "desc", "DENOM_CIA": "nome"})


def _soma(d: pd.DataFrame, filtro: pd.Series) -> pd.Series:
    return d[filtro].groupby(["cd_cvm", "ano"])["valor"].sum(min_count=1)


def _metricas(zf: zipfile.ZipFile, tipo: str, ano: int) -> pd.DataFrame:
    dre = _ler(zf, "DRE", tipo, ano)
    bpa = _ler(zf, "BPA", tipo, ano)
    bpp = _ler(zf, "BPP", tipo, ano)
    if dre.empty:
        return pd.DataFrame()
    # O código do lucro varia (3.09 em bancos, 3.11 nas demais): identifica-se pela descrição.
    nivel = dre["conta"].str.count(r"\.")
    eh_lucro = dre["desc"].str.match(r"^Lucro(?:/| ou )Prejuízo (?:Líquido )?(?:Consolidado )?do Período$") & (nivel == 1)
    eh_ctrl = dre["desc"].str.contains("Controladora") & (nivel == 2) & dre["conta"].str.startswith("3.")
    s = {
        "receita": _soma(dre, dre["conta"] == "3.01"),
        "lucro": _soma(dre, eh_lucro),
        "lucro_ctrl": _soma(dre, eh_ctrl),
    }
    if not bpp.empty:
        # PL é o grupo "Patrimônio Líquido..." de 1º nível (código 2.03 ou 2.08, conforme o plano de contas)
        pl = bpp["desc"].str.startswith("Patrimônio Líquido") & (bpp["conta"].str.count(r"\.") == 1)
        nc = bpp["desc"].str.contains("Não Controladores") & (bpp["conta"].str.count(r"\.") == 2)
        s["patrimonio"] = _soma(bpp, pl)
        s["_nc"] = _soma(bpp, nc)
        s["divida_bruta"] = _soma(bpp, bpp["conta"].isin(["2.01.04", "2.02.01"])
                                  & bpp["desc"].str.startswith("Empréstimos"))
    if not bpa.empty:
        s["caixa"] = _soma(bpa, bpa["conta"].isin(["1.01.01", "1.01.02"]))
    # EBIT (só empresas não financeiras têm a linha "Resultado antes do resultado financeiro") e D&A (DVA 7.04.01)
    s["ebit"] = _soma(dre, (dre["conta"] == "3.05") & dre["desc"].str.startswith("Resultado Antes do Resultado Financeiro"))
    dva = _ler(zf, "DVA", tipo, ano)
    if not dva.empty:
        # Na DVA a depreciação é uma dedução do valor adicionado (vem negativa): usa-se o módulo.
        s["da"] = _soma(dva, (dva["conta"] == "7.04.01") & dva["desc"].str.startswith("Depreciação")).abs()
    # Fluxo de caixa (método direto ou indireto: 6.01 existe nos dois)
    dfc = pd.concat([_ler(zf, "DFC_MD", tipo, ano), _ler(zf, "DFC_MI", tipo, ano)], ignore_index=True)
    if not dfc.empty:
        dfc = dfc.drop_duplicates(["cd_cvm", "ano", "conta"])
        nivel2 = dfc["conta"].str.count(r"\.") == 2
        s["fco"] = _soma(dfc, dfc["conta"] == "6.01")
        investimento = (nivel2 & dfc["conta"].str.startswith("6.02.") & (dfc["valor"] < 0)
                        & dfc["desc"].str.contains("imobilizado|intangível", case=False)
                        & ~dfc["desc"].str.contains("venda|resultado|baixa|recebimento", case=False))
        s["capex"] = -_soma(dfc, investimento)                       # positivo = dinheiro investido
        pago = (nivel2 & dfc["conta"].str.startswith("6.03.") & (dfc["valor"] < 0)
                & dfc["desc"].str.contains(r"dividend|capital próprio|jcp|juros s/", case=False))
        s["dividendos"] = -_soma(dfc, pago)                          # positivo = dinheiro pago ao acionista
    m = pd.DataFrame(s)
    m["patrimonio_ctrl"] = m["patrimonio"] - m["_nc"].fillna(0) if "patrimonio" in m else pd.NA
    m = m.drop(columns=["_nc"], errors="ignore")
    nomes = dre.groupby(["cd_cvm", "ano"])["nome"].first()
    return m.join(nomes).reset_index()


def baixar_historico(progresso=None) -> pd.DataFrame:
    """Baixa as DFPs dos últimos ANOS exercícios e consolida num DataFrame (uma linha por empresa/ano)."""
    hoje = date.today().year
    partes, anos_ok = [], []
    for ano in range(hoje, hoje - ANOS - 1, -1):
        r = requests.get(URL.format(ano=ano), timeout=180)
        if r.status_code == 404:  # exercício ainda não publicado
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            # consolidado tem prioridade; individual só entra se a empresa não publicou consolidado
            partes += [_metricas(zf, "con", ano), _metricas(zf, "ind", ano)]
        anos_ok.append(ano)
        if progresso:
            progresso(len(anos_ok), ANOS + 1, ano)
    todos = pd.concat([p for p in partes if not p.empty], ignore_index=True)
    todos = todos.drop_duplicates(["cd_cvm", "ano"], keep="first")
    # O arquivo do ano corrente só traz exercícios parciais (poucas empresas): descarta anos incompletos.
    por_ano = todos.groupby("ano")["cd_cvm"].nunique()
    completos = por_ano[por_ano >= 0.5 * por_ano.max()].index.sort_values()[-ANOS:]
    return todos[todos["ano"].isin(completos)].sort_values(["cd_cvm", "ano"]).reset_index(drop=True)


def indicadores_anuais(h: pd.DataFrame) -> pd.DataFrame:
    """Margem líquida, ROE e endividamento ano a ano (sobre o histórico de uma empresa)."""
    h = h.copy()
    for c in ("receita", "lucro", "lucro_ctrl", "patrimonio", "patrimonio_ctrl", "divida_bruta", "caixa"):
        # colunas com None chegam como object (sem isso 1/0 levanta erro); as ausentes viram NaN
        h[c] = pd.to_numeric(h[c], errors="coerce") if c in h else float("nan")
    h["mrg_liq"] = h["lucro_ctrl"].fillna(h["lucro"]) / h["receita"].where(h["receita"] != 0) * 100
    base_pl = h["patrimonio_ctrl"].where(h["patrimonio_ctrl"] > 0)
    h["roe"] = h["lucro_ctrl"].fillna(h["lucro"]) / base_pl * 100
    h["divida_liquida"] = h["divida_bruta"] - h["caixa"]
    h["div_bruta_pl"] = h["divida_bruta"] / h["patrimonio"].where(h["patrimonio"] > 0)
    h["div_liq_pl"] = h["divida_liquida"] / h["patrimonio"].where(h["patrimonio"] > 0)

    # Caixa e rentabilidade operacional (colunas podem faltar em bancos de dados antigos)
    for c in ("ebit", "da", "fco", "capex", "dividendos"):
        h[c] = pd.to_numeric(h[c], errors="coerce") if c in h else float("nan")
    lucro = h["lucro_ctrl"].fillna(h["lucro"])
    h["ebitda"] = h["ebit"] + h["da"]
    h["mrg_ebit"] = h["ebit"] / h["receita"].where(h["receita"] != 0) * 100
    h["div_liq_ebitda"] = h["divida_liquida"] / h["ebitda"].where(h["ebitda"] > 0)
    h["fcl"] = h["fco"] - h["capex"].fillna(0)                       # fluxo de caixa livre
    h["payout"] = h["dividendos"] / lucro.where(lucro > 0) * 100
    return h
