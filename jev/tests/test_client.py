import json
import threading
import time
import unittest
import urllib.request
from unittest import mock

from bankmore_jev import client
from bankmore_jev.client import API_URL, DEFAULT_MODEL, JevClient, JevError, parse_response, urllib_transport
from bankmore_jev.questions import OPCOES_GOLPE, QUESTIONS, perguntas

from .servidor import ServidorCru, resposta_http, resposta_json

CHAVE = "chave-de-teste-nao-real"

RESPOSTA = {
    "model": "jev-1.13.0",
    "answers": {
        "golpe": {
            "type": "choice",
            "choice": "falso_parente",
            "probabilities": {"falso_parente": 0.91, "falsa_central": 0.04, "falso_vendedor": 0.02, "outro_golpe": 0.01, "nenhum": 0.02},
            "confidence": 0.88,
        },
        "pressao_de_terceiro": {"type": "noul", "noul": 0.95},
        "instruido_por_terceiro": {"type": "noul", "noul": 0.9},
    },
    "usage": {"input_tokens": 420, "output_tokens": 30},
}


class FakeTransport:
    def __init__(self, status=200, body=None, error=None, espera_s=0.0):
        self.status, self.error, self.espera_s = status, error, espera_s
        self.body = json.dumps(RESPOSTA if body is None else body).encode() if not isinstance(body, bytes) else body
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        if self.espera_s:
            time.sleep(self.espera_s)
        if self.error:
            raise self.error
        return self.status, self.body


def relogio(*instantes):
    valores = iter(instantes)
    return lambda: next(valores)


def via(servidor):
    """Transporte real (urllib), apontado para o servidor local em vez da TypeSafe."""
    return lambda url, headers, body, timeout: urllib_transport(servidor.url + "/v1/systemone", headers, body, timeout)


class ContratoTest(unittest.TestCase):
    def test_monta_a_requisicao_do_contrato(self):
        transporte = FakeTransport()
        cliente = JevClient(CHAVE, timeout_s=1.5, transport=transporte, clock=relogio(10.0, 10.25))
        estado = {"pagamento": {"valor": "de R$ 1 mil a R$ 5 mil"}, "motivo_informado_pelo_cliente": "aluguel"}

        resultado = cliente.ask(estado, QUESTIONS)

        chamada = transporte.calls[0]
        self.assertEqual(chamada["url"], API_URL)
        self.assertEqual(chamada["headers"]["Authorization"], f"Bearer {CHAVE}")
        self.assertEqual(chamada["headers"]["Content-Type"], "application/json")
        self.assertEqual(chamada["timeout"], 1.5)
        self.assertEqual(chamada["body"], {"model": DEFAULT_MODEL, "state": estado, "questions": QUESTIONS})
        self.assertEqual(DEFAULT_MODEL, "jev-1.13.0")
        self.assertEqual(resultado.choices["golpe"].choice, "falso_parente")
        self.assertEqual(resultado.choices["golpe"].confidence, 0.88)
        self.assertEqual(resultado.nouls, {"pressao_de_terceiro": 0.95, "instruido_por_terceiro": 0.9})
        self.assertEqual(resultado.model, "jev-1.13.0")
        self.assertAlmostEqual(resultado.latency_ms, 250.0)

    def test_perguntas_seguem_o_formato_da_api(self):
        for ordem in (False, True):
            for nome, pergunta in perguntas(nenhum_primeiro=ordem).items():
                with self.subTest(nome=nome, nenhum_primeiro=ordem):
                    self.assertIn(pergunta["type"], {"choice", "noul"})
                    self.assertIsInstance(pergunta["instructions"], str)
                    if pergunta["type"] == "choice":
                        self.assertIsInstance(pergunta["criteria"], dict)
                        self.assertEqual(set(pergunta["criteria"]), OPCOES_GOLPE)
                        self.assertTrue(all(isinstance(v, str) and v for v in pergunta["criteria"].values()))
                    else:
                        self.assertNotIn("criteria", pergunta)
        self.assertEqual(next(iter(perguntas(nenhum_primeiro=True)["golpe"]["criteria"])), "nenhum")
        self.assertEqual(list(QUESTIONS["golpe"]["criteria"])[-1], "nenhum")

    def test_respostas_fora_do_contrato_viram_jev_error(self):
        casos = {
            "HTTP 401": FakeTransport(status=401, body={"detail": "invalid key"}),
            "HTTP 529": FakeTransport(status=529, body={}),
            "JSON quebrado": FakeTransport(body=b"<html>erro</html>"),
            "sem answers": FakeTransport(body={"model": "jev"}),
            "answers não é objeto": FakeTransport(body={"answers": []}),
            "choice não é texto": FakeTransport(body={"answers": {"golpe": {"type": "choice", "choice": 1, "confidence": 0.9}}}),
            "confiança fora de [0, 1]": FakeTransport(body={"answers": {"golpe": {"type": "choice", "choice": "nenhum", "confidence": 1.7}}}),
            "confiança booleana": FakeTransport(body={"answers": {"golpe": {"type": "choice", "choice": "nenhum", "confidence": True}}}),
            "confiança em texto": FakeTransport(body={"answers": {"golpe": {"type": "choice", "choice": "nenhum", "confidence": "0.9"}}}),
            "probabilidade NaN": FakeTransport(body=b'{"answers": {"x": {"type": "noul", "noul": NaN}}}'),
            "número enorme": FakeTransport(body=b'{"answers": {"x": {"type": "noul", "noul": 1e999}}}'),
        }
        for nome, transporte in casos.items():
            with self.subTest(nome):
                cliente = JevClient(CHAVE, transport=transporte, clock=relogio(0.0, 0.1))
                with self.assertRaises(JevError) as falha:
                    cliente.ask({}, QUESTIONS)
                self.assertNotIn(CHAVE, str(falha.exception))

    def test_erro_http_traz_o_comeco_do_corpo_sem_a_chave(self):
        corpo = {"detail": f"field questions.golpe.criteria invalid; token {CHAVE}"}
        cliente = JevClient(CHAVE, transport=FakeTransport(status=422, body=corpo), clock=relogio(0.0, 0.1))
        with self.assertRaises(JevError) as falha:
            cliente.ask({}, QUESTIONS)
        self.assertIn("HTTP 422", str(falha.exception))
        self.assertIn("questions.golpe.criteria", str(falha.exception))
        self.assertNotIn(CHAVE, str(falha.exception))

    def test_nenhum_pedaco_da_chave_no_erro_http(self):
        chave = "tsk-abc/def-0123456789-0123456789-xyz"
        corpos = {
            "chave cruzando o corte de 200": json.dumps({"detail": "x" * 170 + " token " + chave}).encode(),
            "chave com barra escapada": json.dumps({"detail": f"token {chave}"}).encode().replace(b"/", b"\\/"),
            "escape de terminal": b'{"detail": "\x1b[2J limpa a tela"}',
        }
        for nome, corpo in corpos.items():
            with self.subTest(nome):
                cliente = JevClient(chave, transport=FakeTransport(status=422, body=corpo), clock=relogio(0.0, 0.1))
                with self.assertRaises(JevError) as falha:
                    cliente.ask({}, QUESTIONS)
                mensagem = str(falha.exception)
                self.assertNotIn(chave[:12], mensagem)
                self.assertNotIn(chave.replace("/", "\\/")[:12], mensagem)
                self.assertTrue(mensagem.isprintable(), repr(mensagem))
                self.assertLessEqual(len(mensagem), 260)

    def test_erro_de_autenticacao_nao_ecoa_o_corpo(self):
        corpo = {"detail": "invalid key " + CHAVE[:5]}
        cliente = JevClient(CHAVE, transport=FakeTransport(status=401, body=corpo), clock=relogio(0.0, 0.1))
        with self.assertRaises(JevError) as falha:
            cliente.ask({}, QUESTIONS)
        self.assertIn("HTTP 401", str(falha.exception))
        self.assertNotIn("invalid key", str(falha.exception))

    def test_json_aninhado_demais_fica_fora_do_contrato(self):
        with self.assertRaises(JevError):
            parse_response(b"[" * 100000 + b"]" * 100000, 1.0)

    def test_probabilidades_invalidas_sao_descartadas_sem_perder_a_resposta(self):
        corpo = {"answers": {"golpe": {"type": "choice", "choice": "nenhum", "confidence": 0.9, "probabilities": {"nenhum": 0.9, "x": "?"}}}}
        resultado = JevClient(CHAVE, transport=FakeTransport(body=corpo), clock=relogio(0.0, 0.1)).ask({}, QUESTIONS)
        self.assertEqual(resultado.choices["golpe"].probabilities, {"nenhum": 0.9})


class ChaveEConfiguracaoTest(unittest.TestCase):
    def test_repr_esconde_a_chave(self):
        cliente = JevClient(CHAVE)
        self.assertNotIn(CHAVE, repr(cliente))
        transporte = FakeTransport()
        JevClient(CHAVE, transport=transporte, clock=relogio(0.0, 0.1)).ask({}, QUESTIONS)
        self.assertNotIn(CHAVE, repr(transporte.calls[0]["headers"]))

    def test_exige_chave_valida_sem_ecoar_o_valor(self):
        for chave in ("", "   ", "abc\r\nX-Injetado: 1", "abc def", "abc\u2026def"):
            with self.subTest(chave=chave), self.assertRaises(ValueError) as falha:
                JevClient(chave)
            if chave.strip():
                self.assertNotIn(chave, str(falha.exception))

    def test_espacos_em_volta_da_chave_sao_ignorados(self):
        transporte = FakeTransport()
        JevClient(f"  {CHAVE}\n", transport=transporte, clock=relogio(0.0, 0.1)).ask({}, QUESTIONS)
        self.assertEqual(transporte.calls[0]["headers"]["Authorization"], f"Bearer {CHAVE}")

    def test_so_aceita_https_e_prazo_positivo(self):
        with self.assertRaises(ValueError):
            JevClient(CHAVE, url="http://api.typesafe.ai/v1/systemone")
        for prazo in (0, -1, 31, float("inf"), float("nan")):
            with self.subTest(prazo=prazo), self.assertRaises(ValueError):
                JevClient(CHAVE, timeout_s=prazo)


class TransporteRealTest(unittest.TestCase):
    """urllib_transport contra um servidor local: o que os fakes não mostram."""

    def setUp(self):
        # Sem proxy: com HTTP_PROXY na máquina, a requisição nem chegaria ao servidor local.
        sem_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}), client._SemRedirect)
        patcher = mock.patch.object(client, "_OPENER", sem_proxy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_chamada_completa(self):
        with ServidorCru(resposta_json(RESPOSTA)) as servidor:
            resultado = JevClient(CHAVE, transport=via(servidor)).ask({"a": "b"}, QUESTIONS)
        self.assertEqual(resultado.choices["golpe"].choice, "falso_parente")
        requisicao = servidor.requisicoes[0]
        self.assertTrue(requisicao.linha.startswith("POST /v1/systemone"))
        self.assertEqual(requisicao.cabecalhos["authorization"], f"Bearer {CHAVE}")
        self.assertEqual(requisicao.json()["state"], {"a": "b"})

    def test_redirect_nao_leva_a_chave_para_outro_host(self):
        with ServidorCru(resposta_json(RESPOSTA)) as outro_host:
            redirect = resposta_http("302 Found", cabecalhos={"Location": outro_host.url + "/roubo"})
            with ServidorCru(redirect) as servidor:
                with self.assertRaises(JevError) as falha:
                    JevClient(CHAVE, transport=via(servidor)).ask({}, QUESTIONS)
        self.assertIn("HTTP 302", str(falha.exception))
        self.assertEqual(outro_host.requisicoes, [])

    def test_falhas_de_protocolo_viram_jev_error(self):
        casos = {
            "corpo truncado": b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{\"answers\"",
            "linha de status inválida": b"HTTP/1.1 abc\r\n\r\n",
            "conexão fechada sem resposta": b"",
        }
        for nome, bruto in casos.items():
            with self.subTest(nome), ServidorCru(bruto) as servidor:
                with self.assertRaises(JevError) as falha:
                    JevClient(CHAVE, transport=via(servidor)).ask({}, QUESTIONS)
                self.assertNotIn(CHAVE, str(falha.exception))
                self.assertIn("Jev inacessível", str(falha.exception))
                self.assertEqual(len(servidor.requisicoes), 1)

    def test_prazo_e_total_mesmo_com_servidor_gotejando(self):
        # Um byte a cada 0,05 s nunca estoura o timeout por operação do socket.
        with ServidorCru(resposta_json(RESPOSTA), intervalo_s=0.05) as servidor:
            inicio = time.perf_counter()
            with self.assertRaises(JevError) as falha:
                JevClient(CHAVE, timeout_s=0.3, transport=via(servidor)).ask({}, QUESTIONS)
            decorrido = time.perf_counter() - inicio
        self.assertIn("não respondeu em 0.3 s", str(falha.exception))
        self.assertLess(decorrido, 1.0)
        self.assertEqual(len(servidor.requisicoes), 1)

    def test_chamadas_lentas_nao_bloqueiam_as_proximas(self):
        with ServidorCru(resposta_json(RESPOSTA), intervalo_s=0.05) as lento, ServidorCru(resposta_json(RESPOSTA)) as rapido:
            for _ in range(6):
                with self.assertRaises(JevError):
                    JevClient(CHAVE, timeout_s=0.15, transport=via(lento)).ask({}, QUESTIONS)
            presas = [t for t in threading.enumerate() if t.name == "jev"]
            self.assertTrue(presas and all(t.daemon for t in presas))  # não seguram o fim do processo
            resultado = JevClient(CHAVE, timeout_s=2.0, transport=via(rapido)).ask({}, QUESTIONS)
        self.assertEqual(resultado.choices["golpe"].choice, "falso_parente")

    def test_prazo_total_com_transporte_lento(self):
        inicio = time.perf_counter()
        with self.assertRaises(JevError):
            JevClient(CHAVE, timeout_s=0.2, transport=FakeTransport(espera_s=0.6)).ask({}, QUESTIONS)
        self.assertLess(time.perf_counter() - inicio, 0.5)

    def test_qualquer_falha_do_transporte_vira_jev_error(self):
        erros = (TimeoutError("timed out"), OSError("connection refused"), ConnectionResetError(),
                 UnicodeEncodeError("latin-1", "x", 0, 1, "fora do latin-1"), RuntimeError("bug"))
        for erro in erros:
            with self.subTest(erro=type(erro).__name__), self.assertRaises(JevError):
                JevClient(CHAVE, transport=FakeTransport(error=erro)).ask({}, QUESTIONS)


if __name__ == "__main__":
    unittest.main()
