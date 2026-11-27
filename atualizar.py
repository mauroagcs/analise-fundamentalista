"""Atualiza o banco local sem interface (para agendar no cron ou no GitHub Actions).

Uso:  python atualizar.py            # só baixa o que está desatualizado
      python atualizar.py --forcar   # baixa tudo de novo
Depois, gere a prévia mobile com:  python gerar_mobile.py [--site PASTA]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import consistencia
import cvm
import db
import fundamentus

DIAS_DETALHES = 15   # setor, dívida e EBIT mudam a cada trimestre
DIAS_HISTORICO = 35  # balanços anuais da CVM: basta conferir de vez em quando
MIN_ACOES = 200      # abaixo disso o site mudou ou nos bloqueou: melhor falhar do que publicar lixo
MAX_FALHAS = 0.10    # fração tolerada de detalhes que não baixaram


def historico_velho() -> bool:
    em = db.meta_get("historico_em")
    return em is None or datetime.now() - datetime.fromisoformat(em) > timedelta(days=DIAS_HISTORICO)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--forcar", action="store_true", help="ignora a idade dos dados e baixa tudo")
    args = ap.parse_args()

    print("Baixando indicadores (resultado.php)…")
    df = fundamentus.baixar_resultado()
    if len(df) < MIN_ACOES:
        raise SystemExit(f"Só {len(df)} ações no resultado.php (esperado ≥ {MIN_ACOES}): site mudou ou bloqueou.")
    db.salvar_indicadores(df)
    tickers = df["ticker"].tolist()

    pendentes = tickers if args.forcar else db.detalhes_desatualizados(tickers, DIAS_DETALHES)
    if pendentes:
        print(f"Baixando setor e dívida de {len(pendentes)} ações…")
        registros, falhas = fundamentus.baixar_detalhes_em_lote(pendentes)
        db.salvar_detalhes(registros)
        if len(falhas) > MAX_FALHAS * len(pendentes):
            raise SystemExit(f"{len(falhas)} de {len(pendentes)} detalhes falharam (ex.: {', '.join(falhas[:5])}).")

    if args.forcar or historico_velho():
        print("Baixando balanços anuais da CVM…")
        db.salvar_historico(cvm.baixar_historico())
    n = consistencia.completar_codigos_cvm(tickers)
    print(f"Pronto: {len(tickers)} ações; {n} códigos CVM novos.")


if __name__ == "__main__":
    main()
