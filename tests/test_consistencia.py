"""Testes do selo de consistência (histórico anual sintético)."""
import math
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import consistencia  # noqa: E402
import cvm  # noqa: E402


def hist(lucros, pl=100.0, divida=100.0, caixa=50.0, ebit=30.0, da=10.0, fco=30.0):
    n = len(lucros)
    return cvm.indicadores_anuais(pd.DataFrame({
        "ano": range(2016, 2016 + n), "receita": [1000.0] * n, "lucro": lucros, "lucro_ctrl": [None] * n,
        "patrimonio": [pl] * n, "patrimonio_ctrl": [pl] * n, "divida_bruta": [divida] * n, "caixa": [caixa] * n,
        "ebit": [ebit] * n, "da": [da] * n, "fco": [fco] * n, "capex": [5.0] * n, "dividendos": [8.0] * n}))


BOA = [20.0 + 2 * i for i in range(10)]


def resultado(h, fin=False):
    r = consistencia.avaliar(h, fin)
    return {nome: ok for nome, ok, _ in r["testes"]}, r


class TestSelo(unittest.TestCase):
    def test_empresa_exemplar_passa_tudo(self):
        t, r = resultado(hist(BOA))
        self.assertTrue(all(v is True for v in t.values()), t)
        self.assertEqual((r["selo_ok"], r["selo_n"]), (5, 5))
        self.assertEqual(r["anos_lucro"], 10)
        self.assertGreater(r["cagr_lucro"], 0)

    def test_prejuizos_reprovam_lucro(self):
        lucros = BOA.copy(); lucros[2] = lucros[5] = -10.0
        t, _ = resultado(hist(lucros))
        self.assertFalse(t["Lucro quase sempre"])
        lucros = BOA.copy(); lucros[4] = -1.0  # um único prejuízo é tolerado
        self.assertTrue(resultado(hist(lucros))[0]["Lucro quase sempre"])

    def test_lucro_decrescente(self):
        self.assertFalse(resultado(hist(BOA[::-1]))[0]["Lucro crescente"])

    def test_roe_baixo(self):
        self.assertFalse(resultado(hist([5.0 + i * 0.1 for i in range(10)]))[0]["ROE alto"])

    def test_divida_alta_e_caixa_liquido(self):
        self.assertFalse(resultado(hist(BOA, divida=400.0, caixa=20.0))[0]["Dívida controlada"])  # 380/40 = 9,5x
        self.assertTrue(resultado(hist(BOA, divida=10.0, caixa=500.0, ebit=-5.0, da=1.0))[0]["Dívida controlada"])  # caixa líquido

    def test_caixa_operacional_negativo(self):
        self.assertFalse(resultado(hist(BOA, fco=-3.0))[0]["Caixa operacional"])

    def test_banco_dispensa_divida_e_caixa(self):
        t, r = resultado(hist(BOA), fin=True)
        self.assertIsNone(t["Dívida controlada"])
        self.assertIsNone(t["Caixa operacional"])
        self.assertEqual(r["selo_n"], 3)

    def test_historico_curto_nao_julga(self):
        t, r = resultado(hist(BOA[:5]))
        self.assertIsNone(t["Lucro quase sempre"])
        self.assertIsNone(t["Lucro crescente"])
        self.assertLess(r["selo_n"], 5)

    def test_cagr_com_lucro_inicial_negativo_e_nan(self):
        self.assertTrue(math.isnan(consistencia.cagr(pd.Series([-5.0, 3.0, 6.0, 9.0]))))


class TestSeriesNovas(unittest.TestCase):
    def test_ebitda_fcl_payout(self):
        h = hist([40.0, 40.0, 40.0])
        self.assertAlmostEqual(h["ebitda"].iloc[0], 40.0)
        self.assertAlmostEqual(h["fcl"].iloc[0], 25.0)        # 30 - 5
        self.assertAlmostEqual(h["payout"].iloc[0], 20.0)     # 8 / 40
        self.assertAlmostEqual(h["div_liq_ebitda"].iloc[0], 1.25)

    def test_ebitda_negativo_nao_gera_multiplo(self):
        h = hist([40.0] * 3, ebit=-50.0, da=5.0)
        self.assertTrue(h["div_liq_ebitda"].isna().all())


if __name__ == "__main__":
    unittest.main()


class TestExtracaoCvm(unittest.TestCase):
    """DFP sintética em memória: confere sinais de D&A (DVA negativa), capex e dividendos (saídas de caixa)."""

    @staticmethod
    def _zip():
        import io
        import zipfile
        cab = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n"

        def linha(conta, desc, valor):
            return f"1;2024-12-31;1;EMPRESA TESTE;000123;DF;REAL;MIL;ÚLTIMO;2024-01-01;2024-12-31;{conta};{desc};{valor};S\n"
        arq = {
            "DRE": [("3.01", "Receita de Venda", 1000), ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", 200),
                    ("3.11", "Lucro/Prejuízo Consolidado do Período", 150)],
            "DVA": [("7.04.01", "Depreciação, Amortização e Exaustão", -50)],        # negativa, como na CVM
            "DFC_MI": [("6.01", "Caixa Líquido Atividades Operacionais", 260),
                       ("6.02.02", "Imobilizado", -80), ("6.02.04", "Recebimento na venda de Ativo Imobilizado", 30),
                       ("6.03.04", "Pagamento de Dividendos", -70)],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for nome, linhas in arq.items():
                z.writestr(f"dfp_cia_aberta_{nome}_con_2024.csv", (cab + "".join(linha(*x) for x in linhas)).encode("latin-1"))
        buf.seek(0)
        return zipfile.ZipFile(buf)

    def test_sinais(self):
        m = cvm._metricas(self._zip(), "con", 2024).iloc[0]
        self.assertEqual(m["da"], 50_000)          # módulo, em R$ (escala MIL)
        self.assertEqual(m["ebit"], 200_000)
        self.assertEqual(m["capex"], 80_000)       # só compra de imobilizado, sem a venda
        self.assertEqual(m["dividendos"], 70_000)
        self.assertEqual(m["fco"], 260_000)
        h = cvm.indicadores_anuais(pd.DataFrame([m]))
        self.assertEqual(h["ebitda"].iloc[0], 250_000)     # EBIT + D&A, nunca menor que o EBIT
        self.assertEqual(h["fcl"].iloc[0], 180_000)
