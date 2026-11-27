"""Persistência local em SQLite (dados/analise.db)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "dados" / "analise.db"

# Campos de detalhes.php que guardamos (nome no banco -> rótulo no site).
DETALHE_CAMPOS = [
    "ticker", "empresa", "tipo", "setor", "subsetor", "valor_mercado", "valor_firma",
    "div_bruta", "div_liquida", "disponibilidades", "ebit_12m", "lucro_12m",
    "receita_12m", "ult_balanco", "atualizado_em",
]

SCHEMA_HISTORICO = """
CREATE TABLE IF NOT EXISTS historico_cvm (
    cd_cvm INTEGER, ano INTEGER, nome TEXT,
    receita REAL, lucro REAL, lucro_ctrl REAL, patrimonio REAL, patrimonio_ctrl REAL,
    divida_bruta REAL, caixa REAL, ebit REAL, da REAL, fco REAL, capex REAL, dividendos REAL,
    PRIMARY KEY (cd_cvm, ano));"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS detalhes ({", ".join(
    c + (" TEXT PRIMARY KEY" if c == "ticker" else
         " TEXT" if c in ("empresa", "tipo", "setor", "subsetor", "ult_balanco", "atualizado_em")
         else " REAL")
    for c in DETALHE_CAMPOS)});
CREATE TABLE IF NOT EXISTS ticker_cvm (ticker TEXT PRIMARY KEY, cd_cvm INTEGER);
{SCHEMA_HISTORICO}
CREATE TABLE IF NOT EXISTS perfil_ia (
    ticker TEXT PRIMARY KEY, conteudo TEXT NOT NULL, modelo TEXT, gerado_em TEXT);
CREATE TABLE IF NOT EXISTS favoritas (
    ticker TEXT PRIMARY KEY, nota TEXT NOT NULL DEFAULT '', adicionada_em TEXT);
"""


def conectar() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    colunas = {r[1] for r in con.execute("PRAGMA table_info(historico_cvm)")}
    if "dividendos" not in colunas:  # versão antiga: o histórico é só cache, recria e pede novo download
        con.executescript("DROP TABLE historico_cvm;" + SCHEMA_HISTORICO)
        con.execute("DELETE FROM meta WHERE chave='historico_em'")
        con.commit()
    return con


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- meta ----------
def meta_get(chave: str) -> str | None:
    with closing(conectar()) as con:
        r = con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
    return r[0] if r else None


def meta_set(chave: str, valor: str) -> None:
    with closing(conectar()) as con, con:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (chave, valor))


# ---------- indicadores (resultado.php) ----------
def salvar_indicadores(df: pd.DataFrame) -> None:
    with closing(conectar()) as con, con:
        df.to_sql("indicadores", con, if_exists="replace", index=False)
    meta_set("indicadores_em", agora())


def ler_tudo() -> pd.DataFrame:
    """Indicadores + detalhes (setor etc.) numa tabela só. Vazia se nunca atualizou."""
    with closing(conectar()) as con:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='indicadores'").fetchone()
        if not existe:
            return pd.DataFrame()
        return pd.read_sql(
            "SELECT i.*, d.empresa, d.tipo, d.setor, d.subsetor, d.valor_mercado, d.valor_firma, "
            "d.div_bruta, d.div_liquida, d.disponibilidades, d.ebit_12m, d.lucro_12m, "
            "d.receita_12m, d.ult_balanco "
            "FROM indicadores i LEFT JOIN detalhes d USING (ticker)", con)


# ---------- detalhes (detalhes.php) ----------
def salvar_detalhes(registros: list[dict]) -> None:
    if not registros:
        return
    cols = ", ".join(DETALHE_CAMPOS)
    marcas = ", ".join(":" + c for c in DETALHE_CAMPOS)
    with closing(conectar()) as con, con:
        con.executemany(
            f"INSERT OR REPLACE INTO detalhes ({cols}) VALUES ({marcas})",
            [{c: r.get(c) for c in DETALHE_CAMPOS} for r in registros])
    meta_set("detalhes_em", agora())


def detalhes_desatualizados(tickers: list[str], dias: int) -> list[str]:
    """Tickers sem detalhes ou com detalhes mais velhos que `dias`."""
    limite = (datetime.now() - pd.Timedelta(days=dias)).isoformat(timespec="seconds")
    with closing(conectar()) as con:
        frescos = {r[0] for r in con.execute(
            "SELECT ticker FROM detalhes WHERE atualizado_em >= ? AND setor IS NOT NULL", (limite,))}
    return [t for t in tickers if t not in frescos]


# ---------- histórico CVM ----------
def salvar_historico(df: pd.DataFrame) -> None:
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM historico_cvm")
        df.to_sql("historico_cvm", con, if_exists="append", index=False)
    meta_set("historico_em", agora())


def ler_historico(cd_cvm: int) -> pd.DataFrame:
    with closing(conectar()) as con:
        return pd.read_sql(
            "SELECT * FROM historico_cvm WHERE cd_cvm=? ORDER BY ano", con, params=(cd_cvm,))


def ler_todo_historico() -> pd.DataFrame:
    with closing(conectar()) as con:
        return pd.read_sql("SELECT * FROM historico_cvm ORDER BY cd_cvm, ano", con)


def mapa_tickers() -> dict[str, int]:
    with closing(conectar()) as con:
        return dict(con.execute("SELECT ticker, cd_cvm FROM ticker_cvm"))


def cd_cvm_do_ticker(ticker: str) -> int | None:
    with closing(conectar()) as con:
        r = con.execute("SELECT cd_cvm FROM ticker_cvm WHERE ticker=?", (ticker,)).fetchone()
    return r[0] if r else None


def salvar_cd_cvm(ticker: str, cd_cvm: int) -> None:
    with closing(conectar()) as con, con:
        con.execute("INSERT OR REPLACE INTO ticker_cvm VALUES (?,?)", (ticker, cd_cvm))


# ---------- favoritas ----------
def ler_favoritas() -> pd.DataFrame:
    with closing(conectar()) as con:
        return pd.read_sql("SELECT ticker, nota, adicionada_em FROM favoritas", con)


def favoritar(ticker: str, nota: str = "") -> None:
    with closing(conectar()) as con, con:
        con.execute("INSERT OR IGNORE INTO favoritas VALUES (?,?,?)", (ticker, nota, agora()))


def salvar_nota(ticker: str, nota: str) -> None:
    with closing(conectar()) as con, con:
        con.execute("UPDATE favoritas SET nota=? WHERE ticker=?", (nota, ticker))


def desfavoritar(ticker: str) -> None:
    with closing(conectar()) as con, con:
        con.execute("DELETE FROM favoritas WHERE ticker=?", (ticker,))


# ---------- perfil gerado por IA (cache: evita pagar de novo pela mesma ação) ----------
def ler_perfil(ticker: str) -> dict | None:
    with closing(conectar()) as con:
        r = con.execute("SELECT conteudo, modelo, gerado_em FROM perfil_ia WHERE ticker=?", (ticker,)).fetchone()
    if not r:
        return None
    return {**json.loads(r[0]), "_modelo": r[1], "_gerado_em": r[2]}


def salvar_perfil(ticker: str, perfil: dict, modelo: str) -> None:
    with closing(conectar()) as con, con:
        con.execute("INSERT OR REPLACE INTO perfil_ia VALUES (?,?,?,?)",
                    (ticker, json.dumps(perfil, ensure_ascii=False), modelo, agora()))
