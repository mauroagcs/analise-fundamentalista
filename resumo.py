"""Resumo da empresa: pontos fortes/fracos pelos números (local) e perfil do negócio via Claude (opcional)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import consistencia
import regras
from regras import fmt

MODELO_IA = "claude-opus-5-5"
MAX_PONTOS = 8


# ------------------------------------------------------------------ pontos pelos números
def _med(df: pd.DataFrame, r: pd.Series, chave: str) -> float:
    return regras.mediana_setor(df, r["setor"], chave) if isinstance(r["setor"], str) else np.nan


def _vs_setor(df, r, chave: str) -> str:
    m = _med(df, r, chave)
    return "" if pd.isna(m) else f" (mediana do setor: {fmt(m, regras.INDICADORES[chave].tipo)})"


def pontos_dados(df: pd.DataFrame, r: pd.Series, h: pd.DataFrame | None = None) -> tuple[list[str], list[str]]:
    """Pontos fortes e fracos deduzidos dos indicadores (e do histórico, se houver). Limiares simples e explícitos."""
    f: list[str] = []
    w: list[str] = []
    ok = lambda k: not pd.isna(r[k])  # noqa: E731
    financeira = bool(r["financeira"])

    if ok("roe"):
        if r["roe"] >= 15:
            f.append(f"Rentabilidade alta: ROE de {fmt(r['roe'], 'pct')}{_vs_setor(df, r, 'roe')}.")
        elif r["roe"] < 8:
            w.append(f"Rentabilidade baixa: ROE de {fmt(r['roe'], 'pct')}{_vs_setor(df, r, 'roe')}.")
    if ok("roic") and not financeira:
        if r["roic"] >= 15:
            f.append(f"Capital bem empregado: ROIC de {fmt(r['roic'], 'pct')}.")
        elif r["roic"] < 8:
            w.append(f"Retorno sobre o capital investido fraco: ROIC de {fmt(r['roic'], 'pct')}.")
    if ok("mrg_liq") and not financeira:
        if r["mrg_liq"] < 0:
            w.append(f"Dá prejuízo: margem líquida de {fmt(r['mrg_liq'], 'pct')}.")
        elif r["mrg_liq"] >= 15:
            f.append(f"Margem líquida confortável: {fmt(r['mrg_liq'], 'pct')}{_vs_setor(df, r, 'mrg_liq')}.")
        elif r["mrg_liq"] < 5:
            w.append(f"Margem líquida apertada: {fmt(r['mrg_liq'], 'pct')}{_vs_setor(df, r, 'mrg_liq')}.")
    if financeira and ok("lucro_12m") and r["lucro_12m"] <= 0:
        w.append("Lucro líquido dos últimos 12 meses não é positivo.")

    if not financeira:
        d = r["div_liq_ebitda"]
        if ok("div_liq_ebitda"):
            if d < 0:
                f.append("Caixa líquido: tem mais caixa do que dívida.")
            elif d <= 1.5:
                f.append(f"Endividamento baixo: Dív.Líq/EBITDA de {fmt(d, 'x')}.")
            elif d > 3:
                w.append(f"Alavancagem elevada: Dív.Líq/EBITDA de {fmt(d, 'x')}{_vs_setor(df, r, 'div_liq_ebitda')}.")
        elif pd.notna(r["div_liquida"]) and r["div_liquida"] > 0:
            w.append("Tem dívida líquida, mas o EBITDA não é positivo: sem folga para pagá-la.")
        if ok("liq_corr"):
            if r["liq_corr"] >= 1.5:
                f.append(f"Folga no curto prazo: liquidez corrente de {fmt(r['liq_corr'], 'x')}.")
            elif r["liq_corr"] < 1:
                w.append(f"Aperto no curto prazo: liquidez corrente de {fmt(r['liq_corr'], 'x')} (abaixo de 1).")

    if ok("cresc_rec_5a"):
        if r["cresc_rec_5a"] >= 10:
            f.append(f"Receita crescendo {fmt(r['cresc_rec_5a'], 'pct')} ao ano em 5 anos.")
        elif r["cresc_rec_5a"] < 0:
            w.append(f"Receita encolheu: {fmt(r['cresc_rec_5a'], 'pct')} ao ano em 5 anos.")
    if ok("dy") and r["dy"] >= 6:
        f.append(f"Boa remuneração ao acionista: dividend yield de {fmt(r['dy'], 'pct')}.")

    # estrutura / liquidez de negociação / classe da ação
    if ok("liq_2m") and r["liq_2m"] < 1_000_000:
        w.append(f"Pouca liquidez na bolsa: {regras.fmt_brl_abrev(r['liq_2m'])}/dia.")
    tipo = r["tipo"] if isinstance(r["tipo"], str) else ""
    if "NM" in tipo.split():
        f.append("Novo Mercado: só ações ON e tag along de 100% — boa governança para o sócio minoritário.")
    elif tipo.split()[:1] in (["PN"], ["PNA"], ["PNB"], ["PNC"]):
        w.append("Ação preferencial: sem direito a voto, e o tag along pode ser menor que 100%.")

    # valuation
    if ok("pl"):
        m = _med(df, r, "pl")
        if r["pl"] <= 0:
            w.append("Sem lucro nos últimos 12 meses: P/L não se aplica.")
        elif r["pl"] <= 10 and (pd.isna(m) or r["pl"] < m):
            f.append(f"Preço baixo frente ao lucro: P/L de {fmt(r['pl'], 'x')}{_vs_setor(df, r, 'pl')}.")
        elif r["pl"] > 25 or (not pd.isna(m) and r["pl"] > 1.5 * m and r["pl"] > 15):
            w.append(f"Preço exigente frente ao lucro: P/L de {fmt(r['pl'], 'x')}{_vs_setor(df, r, 'pl')}.")
    if ok("pvp") and r["pvp"] > 0 and ok("roe"):
        if r["pvp"] < 1 and r["roe"] >= 10:
            f.append(f"Negocia abaixo do patrimônio (P/VP {fmt(r['pvp'], 'x')}) com ROE de {fmt(r['roe'], 'pct')}.")
        elif r["pvp"] > 3 and r["roe"] < 20:
            w.append(f"Paga-se muito pelo patrimônio (P/VP {fmt(r['pvp'], 'x')}) para um ROE de {fmt(r['roe'], 'pct')}.")

    # histórico (CVM)
    if h is not None and len(h) >= 5:
        lucro = h["lucro_ctrl"].fillna(h["lucro"])
        n, pos = len(h), int((lucro > 0).sum())
        if pos == n:
            f.append(f"Lucro em todos os {n} anos analisados ({int(h['ano'].iloc[0])}–{int(h['ano'].iloc[-1])}).")
        elif pos <= 0.7 * n:
            w.append(f"Lucro irregular: prejuízo em {n - pos} dos últimos {n} anos.")
        if lucro.iloc[0] > 0 and lucro.iloc[-1] > 0 and n >= 5:
            cagr = ((lucro.iloc[-1] / lucro.iloc[0]) ** (1 / (n - 1)) - 1) * 100
            if cagr >= 10:
                f.append(f"Lucro crescendo {fmt(cagr, 'pct')} ao ano no período.")
            elif cagr < 0:
                w.append(f"Lucro menor hoje que no início do período ({fmt(cagr, 'pct')} ao ano).")
        ult5 = h["roe"].tail(5).dropna()
        if len(ult5) == 5 and (ult5 >= 12).all():
            f.append("ROE acima de 12% em cada um dos últimos 5 anos: rentabilidade consistente.")
        selo = consistencia.avaliar(h, financeira)
        if selo["selo_n"] >= 3:
            if selo["selo_ok"] >= selo["selo_n"] - 1:
                f.append(f"Selo de consistência alto: passa em {selo['selo_ok']} de {selo['selo_n']} testes de história.")
            elif selo["selo_ok"] <= 1:
                w.append(f"Histórico pouco consistente: passa em só {selo['selo_ok']} de {selo['selo_n']} testes de história.")

    return f[:MAX_PONTOS], w[:MAX_PONTOS]


# ------------------------------------------------------------------ perfil do negócio (Claude)
class ErroIA(RuntimeError):
    pass


SCHEMA = {
    "type": "object",
    "properties": {
        "o_que_faz": {"type": "string", "description": "2 a 3 frases: o que a empresa faz e como ganha dinheiro."},
        "diferenciais": {"type": "array", "items": {"type": "string"},
                         "description": "2 a 4 vantagens competitivas duradouras (marca, escala, custo, regulação, rede...)."},
        "pontos_fortes": {"type": "array", "items": {"type": "string"},
                          "description": "2 a 4 pontos fortes do negócio (não repita indicadores financeiros)."},
        "pontos_fracos": {"type": "array", "items": {"type": "string"},
                          "description": "2 a 4 pontos fracos e riscos do negócio (não repita indicadores financeiros)."},
    },
    "required": ["o_que_faz", "diferenciais", "pontos_fortes", "pontos_fracos"],
    "additionalProperties": False,
}

SISTEMA = (
    "Você é um analista de ações brasileiras que escreve para um investidor de longo prazo (buy and hold, "
    "mentalidade de sócio). Responda em português do Brasil, de forma concreta e breve, sem jargão desnecessário. "
    "Use apenas o que você sabe com segurança sobre a empresa. Se não reconhecer a empresa ou tiver dúvida, diga isso "
    "em 'o_que_faz' em vez de inventar, e deixe as listas vazias. Não cite números (receita, lucro, participação "
    "de mercado) a menos que tenha certeza. Não dê recomendação de compra ou venda. Os indicadores financeiros já são "
    "mostrados separadamente: foque em negócio, mercado, concorrência, regulação e riscos."
)


def gerar_perfil_ia(r: pd.Series, cliente=None) -> dict:
    """Pede ao Claude um perfil qualitativo. Envia apenas dados públicos da empresa (nome, ticker, setor)."""
    import anthropic  # import tardio: o app funciona sem o pacote/chave

    cliente = cliente or anthropic.Anthropic()
    pedido = (f"Empresa: {r['empresa']}\nTicker: {r['ticker']}\nTipo da ação: {r['tipo']}\n"
              f"Setor: {r['setor']}\nSubsetor: {r['subsetor']}\n\n"
              "Faça o perfil do negócio desta empresa listada na B3.")
    try:
        resp = cliente.beta.messages.create(
            model=MODELO_IA, max_tokens=8000, system=SISTEMA,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": pedido}],
        )
    except anthropic.AuthenticationError as e:
        raise ErroIA("Chave da API inválida. Defina ANTHROPIC_API_KEY (veja o README).") from e
    except anthropic.RateLimitError as e:
        raise ErroIA("Limite de uso da API atingido. Tente novamente em instantes.") from e
    except anthropic.APIConnectionError as e:
        raise ErroIA("Sem conexão com a API da Anthropic.") from e
    except anthropic.APIStatusError as e:
        raise ErroIA(f"A API recusou o pedido ({e.status_code}): {e.message}") from e
    except TypeError as e:  # SDK não achou credencial nenhuma
        raise ErroIA("Nenhuma credencial da Anthropic encontrada. Defina ANTHROPIC_API_KEY (veja o README).") from e

    if resp.stop_reason == "refusal":
        raise ErroIA("O modelo recusou gerar este resumo.")
    if resp.stop_reason == "max_tokens":
        raise ErroIA("A resposta foi cortada antes de terminar. Tente de novo.")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        bruto = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErroIA("Resposta do modelo não veio no formato esperado.") from e
    return normalizar(bruto)


def normalizar(bruto: dict) -> dict:
    """Garante o formato (strings e listas de strings) antes de guardar/exibir."""
    lista = lambda v: [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []  # noqa: E731
    return {
        "o_que_faz": str(bruto.get("o_que_faz", "")).strip(),
        "diferenciais": lista(bruto.get("diferenciais")),
        "pontos_fortes": lista(bruto.get("pontos_fortes")),
        "pontos_fracos": lista(bruto.get("pontos_fracos")),
    }
