import argparse
import http.client
import io
import json
import threading
import unittest

from bankmore_jev.api import Aplicacao, ServidorJev, servir
from bankmore_jev.client import JevClient

CHAVE = "chave-teste-nao-real"
ORIGEM = "http://localhost:4200"


class FakeTransport:
    """Jev de mentira: 'falso_parente' com confiança alta e sinais altos."""

    def __init__(self):
        self.estados = []

    def __call__(self, url, headers, body, timeout):
        self.estados.append(json.loads(body)["state"])
        return 200, json.dumps({
            "model": "jev-1.13.0",
            "answers": {
                "golpe": {
                    "type": "choice", "choice": "falso_parente", "confidence": 0.97,
                    "probabilities": {"falso_parente": 0.97, "nenhum": 0.02, "falsa_central": 0.01, "x\x1b": 0.5},
                },
                "pressao_de_terceiro": {"type": "noul", "noul": 0.91},
                "instruido_por_terceiro": {"type": "noul", "noul": 0.42},
            },
        }).encode()


PIX = {
    "valor": "1800,00",
    "hora_local": 19,
    "valor_habitual": 2500,
    "primeiro_pix_para_destino": True,
    "chave_destino_idade_dias": 2,
    "dispositivo_novo": False,
    "motivo_informado": "Meu filho trocou de número, CPF 123.456.789-09, manda no (11) 98765-4321",
    "historico": "Aposentada.",
}


class ApiTest(unittest.TestCase):
    def subir(self, cliente=None, origens=ORIGEM):
        servidor = ServidorJev(Aplicacao(cliente), porta=0, origens=origens)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        self.porta = servidor.server_address[1]
        return servidor

    def pedir(self, metodo, rota, corpo=None, cabecalhos=None, bruto=None):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        self.addCleanup(conexao.close)
        dados = bruto if bruto is not None else (None if corpo is None else json.dumps(corpo).encode())
        enviados = {"Host": f"127.0.0.1:{self.porta}"}
        if dados is not None:
            enviados["Content-Type"] = "application/json"
        enviados.update(cabecalhos or {})
        conexao.request(metodo, rota, body=dados, headers=enviados)
        resposta = conexao.getresponse()
        texto = resposta.read().decode("utf-8")
        return resposta.status, dict(resposta.getheaders()), (json.loads(texto) if texto else None), texto


class RotasTest(ApiTest):
    def test_status_e_cenarios_no_modo_simulado(self):
        self.subir()
        status, _, dados, _ = self.pedir("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(dados["modo"], "simulado")
        status, _, cenarios, _ = self.pedir("GET", "/api/cenarios")
        self.assertEqual(status, 200)
        self.assertEqual(len(cenarios), 8)
        self.assertEqual(cenarios[1]["titulo"], "Golpe do falso parente")
        self.assertNotIn("jev_offline", cenarios[1])

    def test_avalia_cenario_simulado(self):
        self.subir()
        status, _, dados, _ = self.pedir("POST", "/api/avaliar", {"cenario_id": 2})
        self.assertEqual(status, 200)
        self.assertTrue(dados["simulado"])
        self.assertEqual(dados["so_xgboost"], "APROVAR")
        self.assertEqual(dados["decisao"], "RETER_PARA_ANALISE")
        self.assertEqual(dados["fonte_score"], "exemplo")
        self.assertEqual(dados["estado_enviado"]["pagamento"]["valor"], "de R$ 1 mil a R$ 5 mil")

    def test_pix_personalizado_sem_jev_ao_vivo_fica_so_com_o_xgboost(self):
        self.subir()
        status, _, dados, _ = self.pedir("POST", "/api/avaliar", {"pix": PIX, "score_xgboost": 0.1})
        self.assertEqual(status, 200)
        self.assertIsNone(dados["jev"])
        self.assertIn("modo simulado", dados["erro_jev"])
        self.assertEqual(dados["decisao"], "APROVAR")
        self.assertEqual(dados["fonte_score"], "informado")

    def test_pix_personalizado_ao_vivo_mascara_antes_de_enviar(self):
        transporte = FakeTransport()
        self.subir(JevClient(CHAVE, transport=transporte))
        status, _, dados, texto = self.pedir("POST", "/api/avaliar", {"pix": PIX, "score_xgboost": 0.1})
        self.assertEqual(status, 200)
        self.assertEqual(dados["decisao"], "RETER_PARA_ANALISE")
        self.assertEqual(dados["motivos"], ["GOLPE_FALSO_PARENTE", "SINAL_PRESSAO_DE_TERCEIRO"])
        self.assertEqual(dados["jev"]["probabilidades"], {"falso_parente": 0.97, "nenhum": 0.02, "falsa_central": 0.01})
        enviado = json.dumps(transporte.estados[0], ensure_ascii=False)
        for dado in ("123.456.789-09", "98765-4321", "1.800", "1800"):
            self.assertNotIn(dado, enviado)
        self.assertEqual(dados["estado_enviado"], transporte.estados[0])
        self.assertEqual(dados["pix"]["valor"], "1800.00")
        self.assertNotIn(CHAVE, texto)

    def test_status_ao_vivo_nao_expoe_a_chave(self):
        self.subir(JevClient(CHAVE, transport=FakeTransport()))
        _, _, dados, texto = self.pedir("GET", "/api/status")
        self.assertEqual(dados["modo"], "ao_vivo")
        self.assertEqual(dados["modelo"], "jev-1.13.0")
        self.assertNotIn(CHAVE, texto)


class ValidacaoTest(ApiTest):
    def test_entradas_invalidas_viram_400_com_mensagem(self):
        self.subir()
        casos = {
            "cenário inexistente": {"cenario_id": 99},
            "cenário booleano": {"cenario_id": True},
            "sem cenário nem pix": {},
            "corpo não é objeto": [1, 2],
            "valor negativo": {"pix": {**PIX, "valor": -5}},
            "valor em texto inválido": {"pix": {**PIX, "valor": "abc"}},
            "hora 24": {"pix": {**PIX, "hora_local": 24}},
            "hora quebrada": {"pix": {**PIX, "hora_local": 10.5}},
            "booleano como número": {"pix": {**PIX, "primeiro_pix_para_destino": 1}},
            "motivo enorme": {"pix": {**PIX, "motivo_informado": "a" * 2001}},
            "score fora de [0, 1]": {"pix": PIX, "score_xgboost": 1.5},
            "score infinito": {"pix": PIX, "score_xgboost": 1e999},
            "inteiro gigante": {"pix": {**PIX, "hora_local": 10**400}},
            "score inteiro gigante": {"pix": PIX, "score_xgboost": 10**400},
            "surrogate solto": {"pix": {**PIX, "motivo_informado": "oi \ud800 mãe"}},
        }
        for nome, corpo in casos.items():
            with self.subTest(nome):
                status, _, dados, _ = self.pedir("POST", "/api/avaliar", corpo)
                self.assertEqual(status, 400, dados)
                self.assertTrue(dados["erro"])

    def test_protocolo(self):
        self.subir()
        self.assertEqual(self.pedir("POST", "/api/avaliar", bruto=b"{quebrado")[0], 400)
        self.assertEqual(self.pedir("POST", "/api/avaliar", bruto=b'{"cenario_id": 1}', cabecalhos={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.pedir("POST", "/api/avaliar", bruto=b" " * 20000)[0], 413)
        self.assertEqual(self.pedir("GET", "/api/nada")[0], 404)
        self.assertEqual(self.pedir("POST", "/api/status", {"x": 1})[0], 404)

    def test_falha_interna_nao_vaza_detalhe(self):
        servidor = self.subir()

        def quebra(corpo):
            raise RuntimeError("detalhe interno secreto")

        servidor.app.avaliar = quebra
        with self.assertLogs("bankmore_jev", "ERROR"):
            status, _, dados, texto = self.pedir("POST", "/api/avaliar", {"cenario_id": 1})
        self.assertEqual(status, 500)
        self.assertNotIn("secreto", texto)


class OrigemTest(ApiTest):
    def test_cors_so_para_a_origem_permitida(self):
        self.subir()
        status, cabecalhos, _, _ = self.pedir("OPTIONS", "/api/avaliar", cabecalhos={"Origin": ORIGEM})
        self.assertEqual(status, 204)
        self.assertEqual(cabecalhos["Access-Control-Allow-Origin"], ORIGEM)
        status, cabecalhos, _, _ = self.pedir("GET", "/api/status", cabecalhos={"Origin": ORIGEM})
        self.assertEqual(status, 200)
        self.assertEqual(cabecalhos["Access-Control-Allow-Origin"], ORIGEM)

    def test_outra_origem_e_bloqueada(self):
        self.subir()
        for metodo, corpo in (("OPTIONS", None), ("GET", None), ("POST", {"cenario_id": 1})):
            with self.subTest(metodo):
                rota = "/api/status" if metodo == "GET" else "/api/avaliar"
                status, cabecalhos, _, _ = self.pedir(metodo, rota, corpo, cabecalhos={"Origin": "https://site-malicioso.example"})
                self.assertEqual(status, 403)
                self.assertNotIn("Access-Control-Allow-Origin", cabecalhos)

    def test_host_estranho_e_recusado_contra_dns_rebinding(self):
        self.subir()
        status, _, _, _ = self.pedir("GET", "/api/status", cabecalhos={"Host": f"atacante.example:{self.porta}"})
        self.assertEqual(status, 421)


class ServirTest(unittest.TestCase):
    def test_segunda_api_na_mesma_porta_falha_em_vez_de_dividir(self):
        primeira = ServidorJev(Aplicacao(None), porta=0)
        self.addCleanup(primeira.server_close)
        with self.assertRaises(OSError):
            ServidorJev(Aplicacao(None), porta=primeira.server_address[1]).server_close()

    def test_sem_chave_nao_sobe(self):
        erro = io.StringIO()
        args = argparse.Namespace(offline=False, ml_url=None, nenhum_primeiro=False, porta=0)
        self.assertEqual(servir(args, env={}, err=erro), 2)
        self.assertIn("TYPESAFE_API_KEY", erro.getvalue())


if __name__ == "__main__":
    unittest.main()
