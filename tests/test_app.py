"""Testes dos parsers (HTML real salvo) e das regras. Rode: python -m unittest discover -s tests"""
import math
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import fundamentus  # noqa: E402
import regras  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def ler(nome: str) -> str:
    return (FIX / nome).read_bytes().decode("iso-8859-1")


class TestParsers(unittest.TestCase):
    def test_numero_formato_brasileiro(self):
        self.assertEqual(fundamentus._numero("1.012.240.000,00"), 1012240000.0)
        self.assertEqual(fundamentus._numero("-63,96%"), -63.96)
        self.assertEqual(fundamentus._numero(" 33,0%"), 33.0)
        self.assertIsNone(fundamentus._numero("-"))

    def test_resultado(self):
        df = fundamentus.parse_resultado(ler("resultado_amostra.html"))
        self.assertGreater(len(df), 10)
        for col in ("ticker", "pl", "roe", "mrg_liq", "liq_2m", "div_liq_pl", "cresc_rec_5a"):
            self.assertIn(col, df.columns)
        # "0,00" significa "sem dado": vira NaN, exceto liquidez/cotação/dy
        self.assertTrue(df["pl"].isna().any() or (df["pl"] != 0).all())
        self.assertFalse((df["roe"] == 0).any())

    def test_detalhes_industrial(self):
        r = fundamentus.parse_detalhes(ler("detalhes_WEGE3.html"), "WEGE3")
        self.assertEqual(r["setor"], "Máquinas e Equipamentos")
        self.assertEqual(r["subsetor"], "Motores, Compressores e Outros")
        self.assertEqual(r["receita_12m"], 40719500000.0)  # 1ª ocorrência = 12 meses (não o trimestre)
        self.assertEqual(r["div_liquida"], -2585000000.0)
        self.assertEqual(r["valor_firma"], 205812000000.0)

    def test_detalhes_banco_sem_divida(self):
        r = fundamentus.parse_detalhes(ler("detalhes_ITUB4.html"), "ITUB4")
        self.assertEqual(r["setor"], "Intermediários Financeiros")
        self.assertNotIn("div_bruta", r)

    def test_detalhes_invalido(self):
        with self.assertRaises(fundamentus.ErroFundamentus):
            fundamentus.parse_detalhes("<html><body>nada</body></html>", "XXXX3")


def linha(**kw) -> dict:
    base = dict(ticker="TESV3", setor="Máquinas e Equipamentos", liq_2m=5e6, roe=20.0, mrg_liq=10.0,
                pl=10.0, pvp=float("nan"), roic=float("nan"), liq_corr=float("nan"), cresc_rec_5a=float("nan"), dy=float("nan"), tipo="ON", lucro_12m=800.0, ebit_12m=1000.0, ev_ebit=10.0, ev_ebitda=8.0, div_liquida=1000.0, div_bruta=1500.0,
                patrimonio=5000.0)
    base.update(kw)
    return base


def prep(*linhas) -> pd.DataFrame:
    return regras.preparar(pd.DataFrame(linhas))


class TestCvm(unittest.TestCase):
    def test_receita_zero_ou_nula_nao_quebra(self):
        import cvm
        h = pd.DataFrame({"ano": [2024, 2025], "receita": [0, None], "lucro": [5.0, None],
                          "lucro_ctrl": [None, None], "patrimonio": [100.0, 0.0],
                          "patrimonio_ctrl": [100.0, 0.0], "divida_bruta": [10.0, None], "caixa": [None, None]})
        r = cvm.indicadores_anuais(h)
        self.assertTrue(r["mrg_liq"].isna().all())
        self.assertAlmostEqual(r["roe"].iloc[0], 5.0)
        self.assertTrue(math.isnan(r["div_bruta_pl"].iloc[1]))


class TestRegras(unittest.TestCase):
    def test_ebitda_e_divida_liquida_sobre_ebitda(self):
        r = prep(linha()).iloc[0]
        # EV = 1000*10 = 10000 ; EBITDA = 10000/8 = 1250 ; DL/EBITDA = 1000/1250
        self.assertAlmostEqual(r["ebitda_12m"], 1250.0)
        self.assertAlmostEqual(r["div_liq_ebitda"], 0.8)
        self.assertAlmostEqual(r["div_bruta_pl"], 0.3)

    def test_ebitda_invalido_vira_nan(self):
        r = prep(linha(ev_ebitda=-5.0)).iloc[0]
        self.assertTrue(math.isnan(r["div_liq_ebitda"]))

    def test_setor_vazio_vira_nulo(self):
        r = prep(linha(setor="")).iloc[0]
        self.assertTrue(pd.isna(r["setor"]))
        self.assertFalse(r["financeira"])

    def test_banco_sem_div_ebitda_e_marcado(self):
        r = prep(linha(setor="Intermediários Financeiros")).iloc[0]
        self.assertTrue(r["financeira"])
        self.assertEqual(r["aviso"], regras.AVISO_FINANCEIRA)
        self.assertTrue(math.isnan(r["div_liq_ebitda"]))

    def test_filtro_socio_aprova(self):
        self.assertTrue(regras.passa_filtro_socio(prep(linha())).iloc[0])

    def test_filtro_socio_reprova_cada_criterio(self):
        casos = {
            "preferencial": linha(ticker="TESV4"),
            "bdr": linha(ticker="TESV33"),
            "liquidez": linha(liq_2m=1e5),
            "roe": linha(roe=14.0),
            "margem": linha(mrg_liq=-1.0),
            "alavancado": linha(div_liquida=5000.0),  # 5000/1250 = 4x
            "sem roe": linha(roe=float("nan")),
        }
        for nome, l in casos.items():
            with self.subTest(nome):
                self.assertFalse(regras.passa_filtro_socio(prep(l)).iloc[0])

    def test_roe_menor_em_utilities(self):
        self.assertFalse(regras.passa_filtro_socio(prep(linha(roe=12.0))).iloc[0])
        self.assertTrue(regras.passa_filtro_socio(prep(linha(roe=12.0, setor="Energia Elétrica"))).iloc[0])

    def test_banco_passa_sem_checar_div_ebitda(self):
        # banco: sem margem líquida no Fundamentus (NaN) -> vale lucro 12m > 0; Dív./EBITDA dispensado
        df = prep(linha(setor="Intermediários Financeiros", div_liquida=1e9, mrg_liq=float("nan"), lucro_12m=500.0))
        self.assertTrue(regras.passa_filtro_socio(df).iloc[0])

    def test_mediana_e_percentil(self):
        df = prep(*[linha(ticker=f"A{i}3", roe=float(r)) for i, r in enumerate([10, 20, 30, 40, 50])])
        self.assertEqual(regras.mediana_setor(df, "Máquinas e Equipamentos", "roe"), 30.0)
        self.assertEqual(regras.percentil_no_setor(df, "Máquinas e Equipamentos", "roe", 50.0), 80.0)
        # P/L menor é melhor; P/L negativo não é comparável
        self.assertTrue(math.isnan(regras.percentil_no_setor(df, "Máquinas e Equipamentos", "pl", -3.0)))

    def test_mediana_exige_amostra_minima(self):
        df = prep(linha(ticker="A13"), linha(ticker="A23"))
        self.assertTrue(math.isnan(regras.mediana_setor(df, "Máquinas e Equipamentos", "roe")))

    def test_formatacao_ptbr(self):
        self.assertEqual(regras.fmt(1234.567, "x"), "1.234,57")
        self.assertEqual(regras.fmt(31.41, "pct"), "31,4%")
        self.assertEqual(regras.fmt(float("nan"), "pct"), "—")
        self.assertEqual(regras.fmt_brl_abrev(208_397_000_000), "R$ 208,4 bi")


if __name__ == "__main__":
    unittest.main()
