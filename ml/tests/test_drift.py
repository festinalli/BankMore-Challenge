import unittest

import numpy as np

from tests import apoio  # noqa: F401

import drift
from dados import gerar


def referencia(n=20000, seed=1):
    X = gerar(n, 0.02, seed, "base").drop(columns=["is_fraude"])
    return drift.referencia(X, np.linspace(0, 1, 500))


class DriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = referencia()

    def test_psi(self):
        self.assertAlmostEqual(drift.psi([0.5, 0.5], [0.5, 0.5]), 0.0)
        self.assertGreater(drift.psi([0.5, 0.5], [0.9, 0.1]), drift.ALTO)
        self.assertGreater(drift.psi([1.0, 0.0], [0.0, 1.0]), 1.0)  # zero vira EPS, não divide por zero
        with self.assertRaises(ValueError):
            drift.psi([0.5, 0.5], [1.0])

    def test_classificacao(self):
        self.assertEqual([drift.classificar(v) for v in (0.05, 0.10, 0.25, 0.26)],
                         ["estavel", "moderado", "moderado", "alto"])

    def test_features_discretas_sao_medidas_por_valor(self):
        self.assertEqual(set(self.ref["discretas"]),
                         {"tipo", "hora_do_dia", "dow", "count_tx_cpf_1h", "is_autotransferencia"})
        self.assertEqual(set(self.ref["continuas"]), {"valor", "valor_medio_cpf_24h", "valor_p95_cpf_30d"})

    def test_mesma_populacao_estavel_populacao_nova_acusa(self):
        mesma = gerar(3000, 0.02, 2, "base").to_dict(orient="records")
        nova = gerar(3000, 0.02, 2, "nova_fraude").to_dict(orient="records")
        r_mesma = drift.calcular(self.ref, mesma, [])
        r_nova = drift.calcular(self.ref, nova, [])
        self.assertLess(max(r_mesma["features"].values()), drift.MODERADO)
        self.assertGreater(r_nova["features"]["valor_medio_cpf_24h"], drift.ALTO)
        self.assertLess(r_nova["features"]["dow"], drift.MODERADO)  # o dia da semana não mudou
        self.assertIsNone(r_mesma["score"])

    def test_mudanca_em_feature_binaria_e_em_contagem_aparece(self):
        linhas = gerar(2000, 0.02, 2, "base").to_dict(orient="records")
        todas_auto = [{**l, "is_autotransferencia": 1} for l in linhas]
        self.assertGreater(drift.calcular(self.ref, todas_auto, [])["features"]["is_autotransferencia"], drift.ALTO)
        com_uma, com_quatro = ([{**l, "count_tx_cpf_1h": c} for l in linhas] for c in (1, 4))
        psi_1 = drift.calcular(self.ref, com_uma, [])["features"]["count_tx_cpf_1h"]
        psi_4 = drift.calcular(self.ref, com_quatro, [])["features"]["count_tx_cpf_1h"]
        self.assertNotAlmostEqual(psi_1, psi_4, places=2)

    def test_categoria_nova_cai_em_outra(self):
        linhas = [{**l, "tipo": "BOLETO"} for l in gerar(500, 0.02, 2, "base").to_dict(orient="records")]
        self.assertGreater(drift.calcular(self.ref, linhas, [])["features"]["tipo"], drift.ALTO)

    def test_placeholder_fica_fora_do_calculo(self):
        linhas = [{**l, "valor_medio_cpf_24h": None} for l in gerar(1500, 0.02, 2, "base").to_dict(orient="records")]
        resultado = drift.calcular(self.ref, linhas, [], minimo=1000)
        self.assertNotIn("valor_medio_cpf_24h", resultado["features"])
        self.assertIn("valor_medio_cpf_24h", resultado["puladas"])
        self.assertIn("valor", resultado["features"])

    def test_janela(self):
        janela = drift.Janela(tamanho=1200)
        linhas = gerar(1300, 0.02, 2, "base").to_dict(orient="records")
        for linha in linhas[: drift.MINIMO_DE_AMOSTRAS - 1]:
            janela.adicionar(linha, 0.1)
        self.assertIsNone(janela.calcular(self.ref))
        for linha in linhas[drift.MINIMO_DE_AMOSTRAS - 1:]:
            janela.adicionar(linha, 0.1, frozenset({"valor_p95_cpf_30d"}))
        self.assertEqual(len(janela), 1200)
        resultado = janela.calcular(self.ref)
        self.assertEqual(resultado["amostras"], 1200)
        self.assertIn("valor_p95_cpf_30d", resultado["puladas"])  # só ~300 valores reais
        janela.limpar()
        self.assertEqual(len(janela), 0)


if __name__ == "__main__":
    unittest.main()
