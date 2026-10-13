"""O serviço Flask de verdade (test client), com registro em pasta temporária."""
import importlib
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.apoio import treinar

from registro import Registro

TRANSACAO = {"valor": 1800.0, "tipo": "PIX", "hora_do_dia": 19, "dow": 2, "count_tx_cpf_1h": 1,
             "valor_medio_cpf_24h": 300.0, "is_autotransferencia": 0, "valor_p95_cpf_30d": 900.0}


def carregar_app(pasta: Path):
    os.environ.update({"ML_ARTIFACT_DIR": str(pasta), "REDIS_HOST": "", "ML_RECARGA_S": "0",
                       "ML_DRIFT_A_CADA": "50", "ML_THRESHOLD": "0"})
    if "app" in sys.modules:
        return importlib.reload(sys.modules["app"])
    return importlib.import_module("app")


class ServicoComRegistroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._pasta = tempfile.TemporaryDirectory(prefix="bankmore-ml-app-")
        cls.pasta = Path(cls._pasta.name)
        cls.reg = Registro(cls.pasta / "registro")
        treinar(cls.reg, "v1")
        cls.reg.promover("v1", None)
        treinar(cls.reg, "v2", cenario="nova_fraude", seed=7)
        cls.app = carregar_app(cls.pasta)
        cls.cliente = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls._pasta.cleanup()

    def setUp(self):
        # Cada teste começa com v1 em produção, v2 candidata e nada em sombra.
        indice = self.reg.indice()
        indice["versoes"]["v1"]["estado"] = "producao"
        indice["versoes"]["v2"]["estado"] = "candidato"
        indice.update(producao="v1", sombra=None, anteriores=[])
        self.reg.indice_path.write_text(json.dumps(indice), encoding="utf-8")
        self.app.servico._mtime = None
        self.app.servico.talvez_recarregar()

    def prever(self, transacao=TRANSACAO):
        resposta = self.cliente.post("/predict", json={"features": transacao})
        self.assertEqual(resposta.status_code, 200, resposta.get_json())
        return resposta.get_json()

    def test_predict_usa_a_producao_do_registro(self):
        r = self.prever()
        self.assertEqual(r["modelo_versao"], "v1")
        self.assertEqual(r["decisao_recomendada"], "REJEITAR" if r["score"] >= r["threshold"] else "APROVAR")
        self.assertEqual(r["threshold"], self.reg.ficha("v1")["limiar"])
        saude = self.cliente.get("/health").get_json()
        self.assertEqual((saude["model_version"], saude["shadow_version"], saude["registro"]), ("v1", None, True))

    def test_entradas_invalidas_viram_400(self):
        self.assertEqual(self.cliente.post("/predict", data="x", content_type="text/plain").status_code, 400)
        gigante = 10 ** 400
        for corpo in ({"features": [1, 2]}, {"valor": "abc"}, {"valor": math.inf}, {"hora_do_dia": math.inf},
                      {"dow": -math.inf}, {"valor": gigante}, {"dow": gigante}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.cliente.post("/predict", json=corpo).status_code, 400)

    def test_sombra_nao_muda_a_resposta_e_registra_discordancias(self):
        antes = self.prever()
        self.reg.colocar_em_sombra("v2", "teste")
        depois = self.prever()
        for campo in ("score", "decisao_recomendada", "modelo_versao", "threshold"):
            self.assertEqual(antes[campo], depois[campo])
        sombra = self.cliente.get("/sombra").get_json()
        self.assertEqual((sombra["producao"], sombra["sombra"], sombra["predicoes"]), ("v1", "v2", 1))
        self.assertEqual(set(sombra["taxa_discordancia"]), {"modelo", "consumidor"})
        metricas = self.cliente.get("/metrics").get_data(as_text=True)
        self.assertIn("ml_sombra_predicoes_total", metricas)  # contadores acumulam entre testes
        self.assertIn('ml_modelo_info{papel="sombra",versao="v2"} 1.0', metricas)

    def test_falha_na_sombra_nao_derruba_o_predict(self):
        self.reg.colocar_em_sombra("v2", "teste")
        self.prever()

        class Quebrado:
            def predict_proba(self, df):
                raise RuntimeError("modelo em sombra quebrou")

        servico = self.app.servico
        servico.sombra = servico.sombra.__class__("v2", Quebrado(), 0.5, None)
        r = self.prever()
        self.assertEqual(r["modelo_versao"], "v1")
        self.assertEqual(servico.sombra_stats["falhas"], 1)

    def laudo_falso(self, versao="v2"):
        return {"aprovado": True, "candidato": versao, "producao": "v1",
                "criterio": {"hash": self.reg.ficha(versao)["hash_criterio"]}}

    def test_promover_e_reverter_chegam_ao_servico_sem_reiniciar(self):
        self.reg.promover("v2", self.laudo_falso(), "teste")
        self.assertEqual(self.prever()["modelo_versao"], "v2")
        self.reg.reverter("teste de reversão")
        self.assertEqual(self.prever()["modelo_versao"], "v1")
        self.assertIn("ml_recargas_total", self.cliente.get("/metrics").get_data(as_text=True))

    def test_registro_corrompido_mantem_o_modelo_atual(self):
        original = self.reg.indice_path.read_text(encoding="utf-8")
        try:
            self.reg.indice_path.write_text("{ quebrado", encoding="utf-8")
            with self.assertLogs("ml-service", "ERROR"):
                r = self.prever()
            self.assertEqual(r["modelo_versao"], "v1")
        finally:
            self.reg.indice_path.write_text(original, encoding="utf-8")

    def test_drift_aparece_depois_de_amostras_suficientes(self):
        from dados import ALL_FEATURES, gerar
        self.app.servico.janela.limpar()
        self.app.servico.ultimo_drift = None
        self.assertFalse(self.cliente.get("/drift").get_json()["disponivel"])
        for linha in gerar(1000, 0.02, 3, "nova_fraude").to_dict(orient="records"):
            self.prever({k: linha[k] for k in ALL_FEATURES})
        drift = self.cliente.get("/drift").get_json()
        self.assertTrue(drift["disponivel"])
        self.assertEqual(drift["modelo"], "v1")
        self.assertEqual(drift["features"]["valor_medio_cpf_24h"]["nivel"], "alto")
        self.assertIn('ml_feature_psi{feature="valor"}', self.cliente.get("/metrics").get_data(as_text=True))
        # Trocar a produção zera o drift calculado contra a referência anterior.
        self.reg.promover("v2", self.laudo_falso(), "teste")
        self.prever()
        self.assertNotIn('ml_feature_psi{feature="valor"}', self.cliente.get("/metrics").get_data(as_text=True))
        self.assertFalse(self.cliente.get("/drift").get_json()["disponivel"])

    def test_placeholders_ficam_fora_do_drift(self):
        self.app.servico.janela.limpar()
        sem_feature_store = {k: v for k, v in TRANSACAO.items() if k not in ("valor_medio_cpf_24h", "valor_p95_cpf_30d")}
        self.prever(sem_feature_store)
        metricas = self.cliente.get("/metrics").get_data(as_text=True)
        self.assertIn('ml_feature_placeholder_total{feature="valor_medio_cpf_24h"}', metricas)

    def test_modelos_com_indice_corrompido_responde_503(self):
        original = self.reg.indice_path.read_text(encoding="utf-8")
        try:
            self.reg.indice_path.write_text("{ quebrado", encoding="utf-8")
            with self.assertLogs("ml-service", "ERROR"):
                resposta = self.cliente.get("/modelos")
            self.assertEqual(resposta.status_code, 503)
            self.assertEqual(self.prever()["modelo_versao"], "v1")
        finally:
            self.reg.indice_path.write_text(original, encoding="utf-8")

    def test_modelos_mostra_o_registro(self):
        modelos = self.cliente.get("/modelos").get_json()
        self.assertEqual(modelos["producao"], "v1")
        self.assertIn("v2", modelos["versoes"])


class ServicoComSombraQuebradaTest(unittest.TestCase):
    """Uma sombra que não carrega não pode impedir o serviço de subir."""

    def test_sombra_corrompida_na_subida(self):
        with tempfile.TemporaryDirectory(prefix="bankmore-ml-sombra-") as d:
            pasta = Path(d)
            reg = Registro(pasta / "registro")
            treinar(reg, "v1")
            reg.promover("v1", None)
            treinar(reg, "v2", seed=7)
            reg.colocar_em_sombra("v2")
            reg.caminho_modelo("v2").write_bytes(b"isto nao e um modelo")
            with self.assertLogs("ml-service", "ERROR"):
                app = carregar_app(pasta)
            cliente = app.app.test_client()
            r = cliente.post("/predict", json={"features": TRANSACAO})
            self.assertEqual(r.status_code, 200)
            saude = cliente.get("/health").get_json()
            self.assertEqual((saude["model_version"], saude["shadow_version"]), ("v1", None))
            self.assertEqual(saude["registro_pede"]["sombra"], "v2")
            self.assertIn('ml_sombra_falhas_total{etapa="carga"} 1.0', cliente.get("/metrics").get_data(as_text=True))


class ServicoSemRegistroTest(unittest.TestCase):
    """Artefatos antigos (model.joblib + metrics.json) continuam funcionando."""

    def test_cai_nos_artefatos_antigos(self):
        import joblib
        with tempfile.TemporaryDirectory(prefix="bankmore-ml-legado-") as d:
            pasta = Path(d)
            reg = Registro(pasta / "rascunho")
            resultado = treinar(reg, "legado")
            joblib.dump(resultado["model_pipeline"], pasta / "model.joblib")
            (pasta / "metrics.json").write_text(json.dumps({**resultado["metrics"], "model_version": "xgboost-v1"}))
            app = carregar_app(pasta)
            cliente = app.app.test_client()
            r = cliente.post("/predict", json=TRANSACAO).get_json()
            self.assertEqual(r["modelo_versao"], "xgboost-v1")
            self.assertFalse(cliente.get("/drift").get_json()["disponivel"])
            self.assertFalse(cliente.get("/modelos").get_json()["registro"])


if __name__ == "__main__":
    unittest.main()
