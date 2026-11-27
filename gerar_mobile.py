"""Gera dados/app_mobile.html: uma prévia do app para celular, num único arquivo HTML (sem servidor, sem rede).

Uso:  python gerar_mobile.py
É um retrato dos dados do banco no momento da geração: atualize os dados no app e gere de novo.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import consistencia
import cvm
import db
import regras
import resumo

AQUI = Path(__file__).parent
SAIDA = AQUI / "dados" / "app_mobile.html"
MODELO = AQUI / "mobile" / "template.html"


def num(v, casas: int = 2):
    """float -> número JSON (NaN/None -> null)."""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except TypeError:
        return None
    return round(float(v), casas)


def historico(ticker: str):
    cd = db.cd_cvm_do_ticker(ticker)
    h = db.ler_historico(cd) if cd else None
    return cvm.indicadores_anuais(h) if h is not None and not h.empty else None


def empacotar_historico(h) -> dict:
    lucro = h["lucro_ctrl"].fillna(h["lucro"])
    return {
        "a": [int(a) for a in h["ano"]],
        "r": [num(v / 1e9) for v in h["receita"]],        # R$ bi
        "l": [num(v / 1e9) for v in lucro],                # R$ bi
        "roe": [num(v, 1) for v in h["roe"]],
        "ml": [num(v, 1) for v in h["mrg_liq"]],
        "dl": [num(v) for v in h["div_liq_pl"]],
        "eb": [num(v / 1e9) if v == v else None for v in h["ebitda"]],        # EBITDA, R$ bi
        "de": [num(v) for v in h["div_liq_ebitda"]],
        "fc": [num(v / 1e9) if v == v else None for v in h["fco"]],           # caixa das operações
        "fl": [num(v / 1e9) if v == v else None for v in h["fcl"]],           # caixa livre
        "dv": [num(v / 1e9) if v == v else None for v in h["dividendos"]],    # dividendos+JCP pagos
        "po": [num(v, 0) for v in h["payout"]],
    }


def montar_dados() -> dict:
    df = regras.preparar(db.ler_tudo())
    if df.empty:
        raise SystemExit("Banco vazio: abra o app e clique em 'Atualizar dados' primeiro.")
    if db.meta_get("historico_em") is None:
        print("Histórico CVM não baixado: baixando agora…")
        db.salvar_historico(cvm.baixar_historico())
    consistencia.completar_codigos_cvm(df["ticker"].tolist())

    chaves = list(regras.INDICADORES)
    criterios = regras.criterios_socio(df)
    acoes = []
    for i, r in df.iterrows():
        h = historico(r["ticker"])
        fortes, fracos = resumo.pontos_dados(df, r, h)
        selo = consistencia.avaliar(h, bool(r["financeira"])) if h is not None else None
        perfil = db.ler_perfil(r["ticker"])
        setor = r["setor"] if isinstance(r["setor"], str) else None
        acoes.append({
            "t": r["ticker"],
            "n": r["empresa"] if isinstance(r["empresa"], str) else r["ticker"],
            "s": setor,
            "ss": r["subsetor"] if isinstance(r["subsetor"], str) else None,
            "tp": r["tipo"] if isinstance(r["tipo"], str) else "",
            "f": bool(r["financeira"]),
            "c": num(r["cotacao"]),
            "vm": num(r["valor_mercado"], 0),
            "lu": num(r["lucro_12m"], 0),
            "re": num(r["receita_12m"], 0),
            "pa": num(r["patrimonio"], 0),
            "ub": r["ult_balanco"] if isinstance(r["ult_balanco"], str) else None,
            "i": {k: num(r[k]) for k in chaves},
            "cs": [bool(x) for x in criterios.loc[i]],
            "fo": fortes,
            "fr": fracos,
            "pc": {k: num(regras.percentil_no_setor(df, setor, k, r[k]), 0) for k in chaves
                   if k != "liq_2m"} if setor else {},
            "h": empacotar_historico(h) if h is not None else None,
            "sl": {"ok": selo["selo_ok"], "n": selo["selo_n"], "al": selo["anos_lucro"], "t": [[n, o, d] for n, o, d in selo["testes"]]}
                  if selo else None,
            "ia": {k: perfil[k] for k in ("o_que_faz", "diferenciais", "pontos_fortes", "pontos_fracos")}
                  | {"em": perfil["_gerado_em"][:10]} if perfil else None,
        })

    setores = sorted(df["setor"].dropna().unique())
    return {
        "gerado_em": db.meta_get("indicadores_em"),
        "ind": [{"k": k, "r": i.rotulo, "g": i.grupo, "t": i.tipo, "m": i.melhor, "p": i.so_positivo, "a": i.ajuda}
                for k, i in regras.INDICADORES.items()],
        "criterios": list(criterios.columns),
        "criterios_hist": [{"n": n, "d": d} for n, d in consistencia.CRITERIOS],
        "med": {s: {k: num(regras.mediana_setor(df, s, k)) for k in chaves} for s in setores},
        "acoes": acoes,
    }


def main() -> None:
    dados = montar_dados()
    # "</" dentro de <script> fecharia a tag antes da hora
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = MODELO.read_text(encoding="utf-8").replace("/*__DADOS__*/null", js)
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(html, encoding="utf-8")
    print(f"{len(dados['acoes'])} ações -> {SAIDA} ({SAIDA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
