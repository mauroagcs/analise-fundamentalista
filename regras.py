"""Regras de negócio: indicadores derivados, Filtro Sócio, medianas do setor e formatação."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

SETORES_FINANCEIROS = {"Intermediários Financeiros", "Previdência e Seguros"}
SETORES_UTILITIES = {"Energia Elétrica", "Água e Saneamento", "Gás"}
AVISO_FINANCEIRA = "Analisar à parte"


@dataclass(frozen=True)
class Indicador:
    rotulo: str
    grupo: str
    tipo: str             # 'pct' | 'x' | 'brl' | 'preco'
    melhor: str | None    # 'alto' | 'baixo' | None (sem direção clara)
    so_positivo: bool = False  # valores <= 0 não são comparáveis (ex.: P/L de empresa com prejuízo)
    ajuda: str = ""


INDICADORES: dict[str, Indicador] = {
    "pl": Indicador("P/L", "Valuation", "x", "baixo", True,
                    "Preço / Lucro. Anos de lucro atual para pagar o preço da ação."),
    "pvp": Indicador("P/VP", "Valuation", "x", "baixo", True,
                     "Preço / Valor Patrimonial. Quanto o mercado paga sobre o patrimônio."),
    "psr": Indicador("PSR", "Valuation", "x", "baixo", True, "Preço / Receita líquida por ação."),
    "p_ebit": Indicador("P/EBIT", "Valuation", "x", "baixo", True, "Preço / EBIT por ação."),
    "ev_ebitda": Indicador("EV/EBITDA", "Valuation", "x", "baixo", True,
                           "Valor da firma / EBITDA. Considera a dívida da empresa."),
    "dy": Indicador("Div. Yield (%)", "Valuation", "pct", "alto", False,
                    "Dividendos pagos nos últimos 12 meses / preço."),
    "roe": Indicador("ROE (%)", "Rentabilidade", "pct", "alto", False,
                     "Retorno sobre o patrimônio líquido: lucro / PL."),
    "roic": Indicador("ROIC (%)", "Rentabilidade", "pct", "alto", False,
                      "Retorno sobre o capital investido (inclui dívida)."),
    "mrg_bruta": Indicador("Margem bruta (%)", "Margens", "pct", "alto"),
    "mrg_ebit": Indicador("Margem EBIT (%)", "Margens", "pct", "alto",
                          ajuda="Lucro operacional / receita líquida."),
    "mrg_liq": Indicador("Margem líquida (%)", "Margens", "pct", "alto",
                         ajuda="Lucro líquido / receita líquida."),
    "div_liq_ebitda": Indicador("Dív.Líq/EBITDA", "Endividamento", "x", "baixo", False,
                                "Quantos anos de EBITDA para quitar a dívida líquida. Negativo = caixa líquido."),
    "div_bruta_pl": Indicador("Dív.Bruta/PL", "Endividamento", "x", "baixo", False,
                              "Dívida bruta / patrimônio líquido."),
    "div_liq_pl": Indicador("Dív.Líq/PL", "Endividamento", "x", "baixo", False,
                            "Dívida líquida / patrimônio líquido."),
    "liq_corr": Indicador("Liquidez corrente", "Liquidez", "x", "alto", False,
                          "Ativo circulante / passivo circulante. Acima de 1 é folgado."),
    "liq_2m": Indicador("Liquidez 2 meses (R$/dia)", "Liquidez", "brl", "alto", False,
                        "Volume médio diário negociado nos últimos 2 meses."),
    "cresc_rec_5a": Indicador("Cresc. receita 5a (%)", "Crescimento", "pct", "alto", False,
                              "Crescimento anual composto da receita nos últimos 5 anos."),
}

# Indicadores baseados em dívida/EBITDA: não valem para bancos/seguradoras (dívida é matéria-prima deles).
NAO_SE_APLICAM_A_FINANCEIRAS = {"div_liq_ebitda", "div_bruta_pl", "div_liq_pl", "ev_ebitda"}


# ------------------------------------------------------------------ derivados
def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas derivadas e marca bancos/seguradoras."""
    if df.empty:
        return df
    df = df.copy()
    df["setor"] = df["setor"].replace("", np.nan)  # o site traz setor vazio para alguns papéis
    df["financeira"] = df["setor"].isin(SETORES_FINANCEIROS)
    df["utility"] = df["setor"].isin(SETORES_UTILITIES)
    df["aviso"] = np.where(df["financeira"], AVISO_FINANCEIRA, "")

    # EBITDA 12m sem depender do preço: EV = EBIT × (EV/EBIT)  e  EBITDA = EV / (EV/EBITDA)
    ev = df["ebit_12m"] * df["ev_ebit"]
    valido = (ev > 0) & (df["ev_ebitda"] > 0)
    df["ebitda_12m"] = np.where(valido, ev / df["ev_ebitda"], np.nan)
    df["div_liq_ebitda"] = df["div_liquida"] / df["ebitda_12m"]
    df["div_bruta_pl"] = np.where(df["patrimonio"] > 0, df["div_bruta"] / df["patrimonio"], np.nan)

    # Bancos/seguradoras: indicadores de dívida/operacionais não fazem sentido.
    for k in NAO_SE_APLICAM_A_FINANCEIRAS:
        if k in df:
            df.loc[df["financeira"], k] = np.nan
    return df


# ------------------------------------------------------------------ Filtro Sócio
@dataclass
class ParametrosSocio:
    liq_min: float = 1_000_000.0
    roe_min: float = 15.0
    roe_min_utilities: float = 10.0
    div_liq_ebitda_max: float = 3.0
    consistencia_min: int = 0  # 0 = não exige; N = exige selo de consistência >= N (histórico CVM)


def criterios_socio(df: pd.DataFrame, p: ParametrosSocio = ParametrosSocio()) -> pd.DataFrame:
    """Um booleano por critério (NaN conta como reprovado). Bancos/seguradoras: Dív./EBITDA não se aplica."""
    roe_min = np.where(df["utility"], p.roe_min_utilities, p.roe_min)
    out = pd.DataFrame({
        "ON (final 3)": df["ticker"].str.fullmatch(r"[A-Z]{4}3"),  # exclui units (11) e BDRs (33, 34…)
        "Liquidez": df["liq_2m"] >= p.liq_min,
        "ROE": df["roe"] > roe_min,
        # O Fundamentus não informa margem líquida de bancos/seguradoras: vale lucro líquido 12m > 0.
        "Margem líquida > 0": (df["mrg_liq"] > 0) | (df["financeira"] & (df["lucro_12m"] > 0)),
        "Dív.Líq/EBITDA": df["financeira"] | (df["div_liq_ebitda"] < p.div_liq_ebitda_max),
    }, index=df.index)
    if p.consistencia_min:  # critério opcional: história comprovada (ver consistencia.py)
        out[f"Consistência ≥ {p.consistencia_min}"] = df["selo_ok"] >= p.consistencia_min
    return out.fillna(False).astype(bool)


def passa_filtro_socio(df: pd.DataFrame, p: ParametrosSocio = ParametrosSocio()) -> pd.Series:
    return criterios_socio(df, p).all(axis=1)


# ------------------------------------------------------------------ setor
def _validos(serie: pd.Series, chave: str) -> pd.Series:
    s = pd.to_numeric(serie, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if INDICADORES[chave].so_positivo:
        s = s[s > 0]
    return s


def grupo_setor(df: pd.DataFrame, setor: str, liq_min: float = 100_000.0) -> pd.DataFrame:
    return df[(df["setor"] == setor) & (df["liq_2m"] >= liq_min)]


def mediana_setor(df: pd.DataFrame, setor: str, chave: str) -> float:
    g = _validos(grupo_setor(df, setor)[chave], chave)
    return float(g.median()) if len(g) >= 3 else math.nan  # amostra pequena demais não é referência


def percentil_no_setor(df: pd.DataFrame, setor: str, chave: str, valor: float) -> float:
    """% das empresas do setor que esta empresa supera (considerando o que é 'melhor')."""
    ind = INDICADORES[chave]
    g = _validos(grupo_setor(df, setor)[chave], chave)
    if len(g) < 3 or valor is None or pd.isna(valor) or (ind.so_positivo and valor <= 0) or ind.melhor is None:
        return math.nan
    superados = (g < valor) if ind.melhor == "alto" else (g > valor)
    return float(superados.mean() * 100)


# ------------------------------------------------------------------ formatação (pt-BR)
def _br(v: float, casas: int) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt(v, tipo: str) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return "—"
    if tipo == "pct":
        return f"{_br(v, 1)}%"
    if tipo == "x":
        return _br(v, 2)
    if tipo == "preco":
        return f"R$ {_br(v, 2)}"
    if tipo == "brl":
        return fmt_brl_abrev(v)
    return str(v)


def fmt_brl_abrev(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    a = abs(v)
    for lim, suf in ((1e12, "tri"), (1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if a >= lim:
            return f"R$ {_br(v / lim, 1)} {suf}"
    return f"R$ {_br(v, 0)}"
