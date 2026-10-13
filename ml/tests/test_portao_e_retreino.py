import unittest

import numpy as np

from tests.apoio import N_PEQUENO, criterio, pasta_temporaria, treinar

import portao
from dados import ALL_FEATURES, gerar, hash_dados
from registro import ErroDeRegistro, Registro
from retreinar import hash_criterio


class RecallComFprTest(unittest.TestCase):
    def test_limiar_respeita_o_fpr_e_mede_o_recall(self):
        legitimos = np.linspace(0, 0.5, 1000)          # 1% deles acima de ~0.495
        fraudes = np.array([0.2, 0.49, 0.6, 0.9])
        scores = np.concatenate([legitimos, fraudes])
        y = np.array([0] * 1000 + [1] * 4)
        r = portao.recall_com_fpr_fixa(scores, y, 0.01)
        self.assertLessEqual(r["fpr"], 0.01)
        self.assertEqual(r["recall"], 0.5)
        self.assertEqual((r["fraudes"], r["legitimos"]), (4, 1000))

    def test_exige_as_duas_classes(self):
        with self.assertRaises(ValueError):
            portao.recall_com_fpr_fixa([0.1, 0.2], [0, 0], 0.01)


class PortaoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls._pasta = tempfile.TemporaryDirectory(prefix="bankmore-ml-portao-")
        pasta = Path(cls._pasta.name)
        cls.tolerante = criterio(pasta, "tolerante.json", tolerancia=1.0)
        cls.impossivel = criterio(pasta, "impossivel.json", ganho_minimo_por_cenario={"base": 1.0})
        cls.reg = Registro(pasta / "registro")
        treinar(cls.reg, "v1", criterio_path=cls.tolerante)
        cls.reg.promover("v1", None)
        treinar(cls.reg, "v2", seed=7, criterio_path=cls.tolerante)

    @classmethod
    def tearDownClass(cls):
        cls._pasta.cleanup()

    def test_laudo_aprovado_quando_o_criterio_permite(self):
        laudo = portao.avaliar(self.reg, "v2", self.tolerante)
        self.assertTrue(laudo["aprovado"])
        self.assertEqual((laudo["candidato"], laudo["producao"]), ("v2", "v1"))
        self.assertEqual([c["cenario"] for c in laudo["conjuntos"]], ["base", "nova_fraude"])
        av = laudo["criterio"]["avaliacao"]
        self.assertEqual(laudo["conjuntos"][0]["hash_dados"],
                         hash_dados(gerar(av["n"], av["fracao_fraude"], av["seed"], "base", avaliacao=True)))
        for conjunto in laudo["conjuntos"]:
            self.assertEqual(set(conjunto["operacao"]), {"producao", "candidato"})
            self.assertEqual(conjunto["consumidor"]["producao"]["limiar"], portao.LIMIAR_CONSUMIDOR)
            self.assertLessEqual(conjunto["candidato"]["fpr"], laudo["criterio"]["fpr_alvo"])
            lo, hi = conjunto["ic95_diferenca"]
            self.assertLessEqual(lo, hi)
            self.assertEqual(set(conjunto["outros_fpr"]), {"0.100%", "0.300%", "1.000%"})
        self.assertIn("bibliotecas", laudo["ambiente"])

    def test_criterio_mudado_depois_do_treino_e_recusado(self):
        with self.assertRaises(portao.CriterioAlterado):
            portao.avaliar(self.reg, "v2", self.impossivel)
        self.assertNotEqual(hash_criterio(self.tolerante), hash_criterio(self.impossivel))

    def test_ganho_minimo_reprova(self):
        reg = Registro(pasta_temporaria(self) / "registro")
        treinar(reg, "v1", criterio_path=self.impossivel)
        reg.promover("v1", None)
        treinar(reg, "v2", seed=7, criterio_path=self.impossivel)
        laudo = portao.avaliar(reg, "v2", self.impossivel)
        self.assertFalse(laudo["aprovado"])
        self.assertIn("base", laudo["motivo"])
        with self.assertRaises(ErroDeRegistro):
            reg.promover("v2", laudo)

    def test_versao_fora_do_registro_nao_e_avaliada(self):
        for versao in ("v9", "../fora"):
            with self.subTest(versao=versao), self.assertRaises(ErroDeRegistro):
                portao.avaliar(self.reg, versao, self.tolerante)

    def test_regra_estatistica_usa_o_limite_inferior_do_ic(self):
        import json
        from pathlib import Path
        caminho = Path(self._pasta.name) / "estatistico.json"
        dados = json.loads(self.tolerante.read_text(encoding="utf-8"))
        dados.update(tolerancia=0.0, regra_estatistica={"nivel": 0.95, "reamostragens": 200})
        caminho.write_text(json.dumps(dados), encoding="utf-8")
        reg = Registro(pasta_temporaria(self) / "registro")
        treinar(reg, "v1", criterio_path=caminho)
        reg.promover("v1", None)
        treinar(reg, "v1-de-novo", criterio_path=caminho)  # mesma receita, mesmo modelo
        laudo = portao.avaliar(reg, "v1-de-novo", caminho)
        for conjunto in laudo["conjuntos"]:
            self.assertEqual(conjunto["diferenca_recall"], 0.0)
            self.assertEqual(conjunto["regra_sobre"], "limite inferior do IC")
        self.assertTrue(laudo["aprovado"])

    def test_nao_avalia_sem_producao_nem_a_propria_producao(self):
        reg = Registro(pasta_temporaria(self) / "registro")
        treinar(reg, "v1", criterio_path=self.tolerante)
        with self.assertRaises(ErroDeRegistro):
            portao.avaliar(reg, "v1", self.tolerante)
        reg.promover("v1", None)
        with self.assertRaises(ErroDeRegistro):
            portao.avaliar(reg, "v1", self.tolerante)


class RetreinoTest(unittest.TestCase):
    def test_mesmos_argumentos_mesmo_modelo(self):
        a = Registro(pasta_temporaria(self) / "a")
        b = Registro(pasta_temporaria(self) / "b")
        ra = treinar(a, "v1", cenario="nova_fraude", seed=5)
        rb = treinar(b, "v1", cenario="nova_fraude", seed=5)
        fa, fb = a.ficha("v1"), b.ficha("v1")
        self.assertEqual(fa["dados"]["hash"], fb["dados"]["hash"])
        self.assertEqual(fa["hash_codigo"], fb["hash_codigo"])
        self.assertEqual(fa["metricas"], fb["metricas"])
        amostra = gerar(500, 0.02, 99, "base")[ALL_FEATURES]
        np.testing.assert_allclose(ra["model_pipeline"].predict_proba(amostra), rb["model_pipeline"].predict_proba(amostra))

    def test_ficha_tem_o_necessario_para_refazer_e_auditar(self):
        reg = Registro(pasta_temporaria(self) / "registro")
        treinar(reg, "v1")
        ficha = reg.ficha("v1")
        for campo in ("criado_em", "dados", "hash_codigo", "hash_criterio", "bibliotecas", "plataforma", "limiar", "metricas", "referencia_drift", "comando"):
            self.assertIn(campo, ficha)
        self.assertTrue(ficha["dados"]["sintetico"])
        self.assertEqual(ficha["dados"]["n_amostras"], N_PEQUENO)
        self.assertIn("--cenario base", ficha["comando"])
        self.assertEqual(set(ficha["referencia_drift"]), {"continuas", "discretas", "score"})

    def test_versao_repetida_nao_retreina(self):
        reg = Registro(pasta_temporaria(self) / "registro")
        treinar(reg, "v1")
        with self.assertRaises(ErroDeRegistro):
            treinar(reg, "v1")


if __name__ == "__main__":
    unittest.main()
