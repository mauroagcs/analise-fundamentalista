"""Testes do resumo: pontos pelos números, chamada ao Claude (cliente simulado) e cache."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db  # noqa: E402
import regras  # noqa: E402
import resumo  # noqa: E402
from test_app import linha, prep  # noqa: E402
from test_consistencia import hist  # noqa: E402


def pontos(**kw):
    outros = [linha(ticker=f"B{i}3", roe=10.0, pl=12.0, mrg_liq=8.0) for i in range(4)]
    df = prep(linha(**kw), *outros)
    return resumo.pontos_dados(df, df.iloc[0])


class TestPontosDados(unittest.TestCase):
    def test_empresa_forte(self):
        f, w = pontos(roe=30.0, mrg_liq=20.0, div_liquida=-500.0, tipo="ON NM", dy=7.0, liq_corr=2.0,
                      cresc_rec_5a=12.0)
        txt = " ".join(f)
        for trecho in ("ROE de 30,0%", "Caixa líquido", "Novo Mercado", "dividend yield", "liquidez corrente"):
            self.assertIn(trecho, txt)
        self.assertEqual(w, [])

    def test_empresa_fraca(self):
        f, w = pontos(roe=3.0, mrg_liq=-2.0, div_liquida=6000.0, tipo="PN", liq_2m=2e5, liq_corr=0.7,
                      cresc_rec_5a=-4.0, pl=-5.0)
        txt = " ".join(w)
        for trecho in ("ROE de 3,0%", "prejuízo", "Alavancagem elevada", "preferencial", "Pouca liquidez",
                       "abaixo de 1", "Receita encolheu", "Sem lucro"):
            self.assertIn(trecho, txt)

    def test_banco_nao_cita_divida(self):
        f, w = pontos(setor="Intermediários Financeiros", roe=20.0, mrg_liq=float("nan"), lucro_12m=900.0)
        todo = " ".join(f + w)
        self.assertNotIn("EBITDA", todo)
        self.assertNotIn("liquidez corrente", todo)
        self.assertIn("ROE de 20,0%", todo)

    def test_historico(self):
        h = hist([100.0 * 1.2 ** i for i in range(10)])
        outros = [linha(ticker=f"B{i}3") for i in range(4)]
        df = prep(linha(), *outros)
        f, _ = resumo.pontos_dados(df, df.iloc[0], h)
        txt = " ".join(f)
        self.assertIn("todos os 10 anos", txt)
        self.assertIn("Lucro crescendo", txt)
        self.assertIn("últimos 5 anos", txt)
        self.assertIn("Selo de consistência alto", txt)

    def test_limite_de_pontos(self):
        f, w = pontos(roe=30.0, roic=30.0, mrg_liq=30.0, div_liquida=-5.0, liq_corr=3.0, cresc_rec_5a=20.0,
                      dy=9.0, pl=5.0, pvp=0.8, tipo="ON NM")
        self.assertLessEqual(len(f), resumo.MAX_PONTOS)


def cliente_falso(texto=None, stop="end_turn", erro=None):
    def create(**kw):
        if erro:
            raise erro
        cria.chamadas.append(kw)
        return NS(stop_reason=stop, content=[NS(type="thinking", thinking=""), NS(type="text", text=texto)])
    cria = NS(chamadas=[])
    create.__self__ = None
    cria.create = create
    return NS(beta=NS(messages=cria)), cria


LINHA = pd.Series({"ticker": "WEGE3", "empresa": "WEG SA ON N1", "tipo": "ON N1",
                   "setor": "Máquinas e Equipamentos", "subsetor": "Motores"})
OK = json.dumps({"o_que_faz": "Fabrica motores.", "diferenciais": ["Escala", " "], "pontos_fortes": ["A"],
                 "pontos_fracos": ["B"], "extra": "ignorado"})


class TestPerfilIA(unittest.TestCase):
    def test_sucesso_e_parametros(self):
        cli, cria = cliente_falso(OK)
        p = resumo.gerar_perfil_ia(LINHA, cli)
        self.assertEqual(p["o_que_faz"], "Fabrica motores.")
        self.assertEqual(p["diferenciais"], ["Escala"])  # item vazio descartado
        self.assertNotIn("extra", p)
        kw = cria.chamadas[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("temperature", kw)
        self.assertNotIn("thinking", kw)

    def test_recusa(self):
        with self.assertRaisesRegex(resumo.ErroIA, "recusou"):
            resumo.gerar_perfil_ia(LINHA, cliente_falso("", stop="refusal")[0])

    def test_cortada(self):
        with self.assertRaisesRegex(resumo.ErroIA, "cortada"):
            resumo.gerar_perfil_ia(LINHA, cliente_falso("{", stop="max_tokens")[0])

    def test_json_invalido(self):
        with self.assertRaisesRegex(resumo.ErroIA, "formato"):
            resumo.gerar_perfil_ia(LINHA, cliente_falso("não é json")[0])

    def test_sem_credencial(self):
        with self.assertRaisesRegex(resumo.ErroIA, "credencial"):
            resumo.gerar_perfil_ia(LINHA, cliente_falso(erro=TypeError("no auth"))[0])


class TestCachePerfil(unittest.TestCase):
    def test_ida_e_volta(self):
        original = db.DB_PATH
        with tempfile.TemporaryDirectory() as d:
            db.DB_PATH = Path(d) / "t.db"
            try:
                self.assertIsNone(db.ler_perfil("WEGE3"))
                db.salvar_perfil("WEGE3", resumo.normalizar(json.loads(OK)), "m")
                p = db.ler_perfil("WEGE3")
                self.assertEqual(p["o_que_faz"], "Fabrica motores.")
                self.assertEqual(p["_modelo"], "m")
            finally:
                db.DB_PATH = original


if __name__ == "__main__":
    unittest.main()
