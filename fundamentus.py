"""Coleta de dados do fundamentus.com.br (resultado.php e detalhes.php)."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.fundamentus.com.br"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# Cabeçalho do site (normalizado) -> nome da coluna no app.
COLUNAS_RESULTADO = {
    "papel": "ticker", "cotação": "cotacao", "p/l": "pl", "p/vp": "pvp", "psr": "psr",
    "div.yield": "dy", "p/ativo": "p_ativo", "p/cap.giro": "p_cap_giro", "p/ebit": "p_ebit",
    "p/ativcirc.liq": "p_ativ_circ_liq", "ev/ebit": "ev_ebit", "ev/ebitda": "ev_ebitda",
    "mrgbruta": "mrg_bruta", "mrgebit": "mrg_ebit", "mrg.líq.": "mrg_liq",
    "liq.corr.": "liq_corr", "roic": "roic", "roe": "roe", "liq.2meses": "liq_2m",
    "patrim.líq": "patrimonio", "dív.líq/patrim.": "div_liq_pl",
    "dív.brut/patrim.": "div_bruta_pl_site", "cresc.rec.5a": "cresc_rec_5a",
}
# No resultado.php, "0,00" significa "sem dado" — exceto nestas colunas.
ZERO_E_VALIDO = {"cotacao", "dy", "liq_2m"}

# Rótulos de detalhes.php -> campo do banco (usa a 1ª ocorrência = últimos 12 meses).
ROTULOS_DETALHE = {
    "Empresa": "empresa", "Tipo": "tipo", "Setor": "setor", "Subsetor": "subsetor",
    "Valor de mercado": "valor_mercado", "Valor da firma": "valor_firma",
    "Dív. Bruta": "div_bruta", "Dív. Líquida": "div_liquida",
    "Disponibilidades": "disponibilidades", "EBIT": "ebit_12m",
    "Lucro Líquido": "lucro_12m", "Receita Líquida": "receita_12m",
    "Últ balanço processado": "ult_balanco",
}
TEXTO = {"empresa", "tipo", "setor", "subsetor", "ult_balanco"}


class ErroFundamentus(RuntimeError):
    pass


def _numero(txt: str) -> float | None:
    """'1.234,56%' -> 1234.56 ; vazio/inválido -> None."""
    t = txt.replace("%", "").replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _get(url: str, params: dict | None = None, tentativas: int = 3) -> str:
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.content.decode("iso-8859-1")
        except requests.RequestException as e:
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise ErroFundamentus(f"Falha ao acessar {url}: {ultimo}")


def _normaliza(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


# ---------------------------------------------------------------- resultado.php
def parse_resultado(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    tabela = soup.find("table", id="resultado")
    if tabela is None:
        raise ErroFundamentus("Tabela de resultados não encontrada (o site mudou?).")
    cabecalho = [_normaliza(th.get_text()) for th in tabela.find("thead").find_all("th")]
    nomes = [COLUNAS_RESULTADO.get(c) for c in cabecalho]
    if "ticker" not in nomes or "roe" not in nomes:
        raise ErroFundamentus(f"Cabeçalho inesperado no resultado.php: {cabecalho}")

    linhas = []
    for tr in tabela.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != len(nomes):
            continue
        reg = {}
        for nome, td in zip(nomes, tds):
            if nome is None:
                continue
            txt = td.get_text(strip=True)
            reg[nome] = txt if nome == "ticker" else _numero(txt)
        linhas.append(reg)

    df = pd.DataFrame(linhas)
    for c in df.columns:
        if c != "ticker" and c not in ZERO_E_VALIDO:
            df.loc[df[c] == 0, c] = float("nan")
    return df


def baixar_resultado() -> pd.DataFrame:
    df = parse_resultado(_get(f"{BASE}/resultado.php"))
    # Papéis sem negociação (liquidez 0) são ruído: não dá para comprar.
    return df[df["liq_2m"] > 0].reset_index(drop=True)


# ---------------------------------------------------------------- detalhes.php
def parse_detalhes(html: str, ticker: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    pares: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        for rotulo, dado in zip(tds, tds[1:]):
            if "label" in rotulo.get("class", []) and "data" in dado.get("class", []):
                span = rotulo.find("span", class_="txt")
                if span:
                    pares.setdefault(span.get_text(strip=True), dado.get_text(" ", strip=True))
    if "Setor" not in pares:
        raise ErroFundamentus(f"Página de detalhes sem setor para {ticker}.")

    reg: dict = {"ticker": ticker}
    for rotulo, campo in ROTULOS_DETALHE.items():
        valor = pares.get(rotulo)
        if valor is None:
            continue
        reg[campo] = valor if campo in TEXTO else _numero(valor)
    return reg


def baixar_detalhes(ticker: str) -> dict:
    reg = parse_detalhes(_get(f"{BASE}/detalhes.php", {"papel": ticker}), ticker)
    reg["atualizado_em"] = pd.Timestamp.now().isoformat(timespec="seconds")
    return reg


def baixar_detalhes_em_lote(tickers: list[str], progresso=None, workers: int = 6):
    """Baixa detalhes em paralelo (educado: poucas conexões). Retorna (registros, falhas)."""
    registros, falhas = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(baixar_detalhes, t): t for t in tickers}
        for i, f in enumerate(as_completed(futuros), 1):
            try:
                registros.append(f.result())
            except ErroFundamentus:
                falhas.append(futuros[f])
            if progresso:
                progresso(i, len(tickers))
    return registros, falhas


# ---------------------------------------------------------------- código CVM
def obter_cd_cvm(ticker: str) -> int | None:
    """Código CVM da companhia (usado para casar com as DFPs). Vem nas imagens de graficos.php."""
    html = _get(f"{BASE}/graficos.php", {"papel": ticker, "tipo": 3})
    m = re.search(r"codcvm=(\d+)", html)
    return int(m.group(1)) if m else None
