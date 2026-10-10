import argparse
import io
import json
import re
import unittest
from decimal import Decimal

from bankmore_jev.demo import carregar_cenarios, executar, pix_do_cenario, resumo, score_do_fraud_ml

from .servidor import ServidorCru, resposta_http, resposta_json

CHAVE = "chave-teste-nao-real"
FAIXAS = {"até R$ 200", "de R$ 200 a R$ 1 mil", "de R$ 1 mil a R$ 5 mil", "de R$ 5 mil a R$ 20 mil", "acima de R$ 20 mil"}


def args(**overrides):
    valores = {"offline": True, "ml_url": None, "cenario": None, "json": False, "sem_cor": True, "nenhum_primeiro": False}
    valores.update(overrides)
    return argparse.Namespace(**valores)


def rodar_json(**kwargs):
    saida = io.StringIO()
    codigo = executar(args(json=True, **kwargs.pop("args", {})), out=saida, **kwargs)
    return codigo, [json.loads(linha) for linha in saida.getvalue().splitlines()], saida.getvalue()


class FakeTransport:
    """Jev de mentira: responde 'falso_parente' para tudo, com 200 ms."""

    def __init__(self, status=200, erro=None):
        self.status, self.erro = status, erro
        self.corpos = []

    def __call__(self, url, headers, body, timeout):
        self.corpos.append(json.loads(body))
        if self.erro:
            raise self.erro
        if self.status != 200:
            return self.status, b"{}"
        return 200, json.dumps({
            "model": "jev-1.13.0",
            "answers": {
                "golpe": {"type": "choice", "choice": "falso_parente", "confidence": 0.9, "probabilities": {}},
                "pressao_de_terceiro": {"type": "noul", "noul": 0.9},
                "instruido_por_terceiro": {"type": "noul", "noul": 0.9},
            },
        }).encode()


class OfflineTest(unittest.TestCase):
    def test_offline_reproduz_as_decisoes_esperadas(self):
        codigo, resultados, _ = rodar_json(env={})
        self.assertEqual(codigo, 0)
        esperado = {c["id"]: c["acao_esperada_offline"] for c in carregar_cenarios()}
        self.assertEqual({r["id"]: r["decisao"] for r in resultados}, esperado)

    def test_o_caso_que_so_o_jev_pega(self):
        _, [resultado], _ = rodar_json(args={"cenario": 2}, env={})
        self.assertEqual(resultado["so_xgboost"], "APROVAR")
        self.assertEqual(resultado["decisao"], "RETER_PARA_ANALISE")

    def test_json_e_ascii_valido_em_qualquer_code_page(self):
        _, _, bruto = rodar_json(env={})
        self.assertTrue(bruto.isascii())
        self.assertIn("Aluguel do m\\u00eas", bruto)

    def test_tabela_avisa_que_e_simulado_e_resume_os_numeros(self):
        saida = io.StringIO()
        executar(args(), out=saida, env={})
        texto = saida.getvalue()
        self.assertIn("SIMULADAS", texto)
        self.assertIn("Golpe do falso parente", texto)
        self.assertIn("RETER PARA ANÁLISE", texto)
        self.assertIn("o XGBoost sozinho aprovaria 5 de 5; desses, o Jev segurou 5", texto)
        self.assertIn("Pix legítimos com atrito a mais por causa do Jev: 0 de 2.", texto)
        self.assertNotIn("Latência do Jev", texto)  # simulado não tem latência

    def test_cenario_inexistente(self):
        erro = io.StringIO()
        self.assertEqual(executar(args(cenario=99), out=io.StringIO(), err=erro, env={}), 2)


class AoVivoTest(unittest.TestCase):
    def test_exige_chave(self):
        for env in ({}, {"TYPESAFE_API_KEY": "  "}):
            with self.subTest(env=env):
                erro = io.StringIO()
                self.assertEqual(executar(args(offline=False), out=io.StringIO(), err=erro, env=env), 2)
                self.assertIn("TYPESAFE_API_KEY", erro.getvalue())

    def test_valida_o_prazo(self):
        for valor, codigo in (("2,5", 0), ("0.5", 0), ("abc", 2), ("-1", 2), ("0", 2), ("999", 2)):
            with self.subTest(valor=valor):
                erro = io.StringIO()
                env = {"TYPESAFE_API_KEY": CHAVE, "JEV_TIMEOUT_S": valor}
                resultado = executar(args(offline=False, json=True, cenario=1), out=io.StringIO(), err=erro, env=env, transport=FakeTransport())
                self.assertEqual(resultado, codigo, erro.getvalue())

    def test_envia_estado_sem_dados_pessoais_nem_valor_exato(self):
        transporte = FakeTransport()
        codigo, resultados, bruto = rodar_json(args={"offline": False}, env={"TYPESAFE_API_KEY": CHAVE}, transport=transporte)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(transporte.corpos), len(carregar_cenarios()))
        for corpo, cenario in zip(transporte.corpos, carregar_cenarios()):
            estado = corpo["state"]
            self.assertEqual(set(estado), {"pagamento", "motivo_informado_pelo_cliente", "historico_do_cliente"})
            self.assertIn(estado["pagamento"]["valor"], FAIXAS)
            texto = json.dumps(estado, ensure_ascii=False)
            self.assertIsNone(re.search(r"\d{4,}", texto), texto)
            self.assertNotIn(cenario["pix"]["valor"].split(".")[0], texto)
        self.assertNotIn(CHAVE, bruto)
        self.assertTrue(all(r["jev"]["modelo"] == "jev-1.13.0" for r in resultados))

    def test_nenhum_primeiro_inverte_a_ordem_das_opcoes(self):
        transporte = FakeTransport()
        rodar_json(args={"offline": False, "cenario": 1, "nenhum_primeiro": True}, env={"TYPESAFE_API_KEY": CHAVE}, transport=transporte)
        self.assertEqual(next(iter(transporte.corpos[0]["questions"]["golpe"]["criteria"])), "nenhum")

    def test_fail_open_quando_o_jev_falha(self):
        for nome, transporte in (("HTTP 500", FakeTransport(status=500)), ("erro inesperado", FakeTransport(erro=RuntimeError("boom")))):
            with self.subTest(nome), self.assertLogs("bankmore_jev", "WARNING"):
                codigo, resultados, bruto = rodar_json(args={"offline": False}, env={"TYPESAFE_API_KEY": CHAVE}, transport=transporte)
                self.assertEqual(codigo, 0)
                for r in resultados:
                    self.assertEqual(r["decisao"], r["so_xgboost"])
                    self.assertIsNone(r["jev"])
                    self.assertIsNotNone(r["erro_jev"])
                self.assertNotIn(CHAVE, bruto)

    def test_tabela_ao_vivo_mostra_latencia_e_modelo(self):
        saida = io.StringIO()
        executar(args(offline=False), out=saida, env={"TYPESAFE_API_KEY": CHAVE}, transport=FakeTransport())
        texto = saida.getvalue()
        self.assertIn(f"Latência do Jev ({len(carregar_cenarios())} chamadas, jev-1.13.0)", texto)
        self.assertNotIn("SIMULADAS", texto)
        self.assertNotIn("falhou", texto)
        self.assertIn("Pix legítimos com atrito a mais por causa do Jev: 1 de 2 (cenário 1).", texto)


class TabelaTest(unittest.TestCase):
    def test_tabela_conta_as_falhas_do_jev(self):
        saida = io.StringIO()
        with self.assertLogs("bankmore_jev", "WARNING"):
            executar(args(offline=False), out=saida, env={"TYPESAFE_API_KEY": CHAVE}, transport=FakeTransport(status=500))
        texto = saida.getvalue()
        total = len(carregar_cenarios())
        self.assertIn(f"O Jev falhou em {total} chamada(s); nelas valeu a decisão do XGBoost (fail-open).", texto)
        self.assertIn("desses, o Jev segurou 0", texto)
        self.assertNotIn("Latência do Jev", texto)

    def test_tabela_nao_repassa_escapes_de_terminal(self):
        def malicioso(url, headers, body, timeout):
            return 200, json.dumps({
                "model": "jev\x1b]0;titulo\x07-1.13.0",
                "answers": {
                    "golpe": {"type": "choice", "choice": "\x1b[2J\rAPROVAR", "confidence": 0.99},
                    "pressao_de_terceiro": {"type": "noul", "noul": 0.0},
                    "instruido_por_terceiro": {"type": "noul", "noul": 0.0},
                },
            }).encode()

        saida = io.StringIO()
        executar(args(offline=False, cenario=1), out=saida, env={"TYPESAFE_API_KEY": CHAVE}, transport=malicioso)
        texto = saida.getvalue()
        for controle in ("\x1b", "\x07", "\r"):
            self.assertNotIn(controle, texto)
        self.assertIn("(rótulo desconhecido)", texto)

    def test_golpe_que_o_xgboost_recusou_nao_conta_como_merito_do_jev(self):
        resultados = [
            {"id": 1, "categoria": "golpe", "so_xgboost": "RECUSAR", "decisao": "RECUSAR", "jev": None, "erro_jev": "x"},
            {"id": 2, "categoria": "golpe", "so_xgboost": "APROVAR", "decisao": "APROVAR", "jev": None, "erro_jev": "x"},
        ]
        self.assertIn("o XGBoost sozinho aprovaria 1 de 2; desses, o Jev segurou 0", "\n".join(resumo(resultados)))


class FraudMlTest(unittest.TestCase):
    def setUp(self):
        self.pix = pix_do_cenario(next(c for c in carregar_cenarios() if c["id"] == 6))

    def test_envia_as_features_e_le_o_score(self):
        with ServidorCru(resposta_json({"score": 0.42})) as servidor:
            self.assertEqual(score_do_fraud_ml(servidor.url, self.pix), 0.42)
        requisicao = servidor.requisicoes[0]
        self.assertTrue(requisicao.linha.startswith("POST /predict"))
        self.assertEqual(requisicao.json(), {"features": {
            "valor": 45000.0, "tipo": "PIX", "hora_do_dia": 3, "dow": 1, "count_tx_cpf_1h": 0,
            "is_autotransferencia": 0, "valor_p95_cpf_30d": 1500.0, "valor_medio_cpf_24h": 200.0,
        }})
        self.assertEqual(self.pix.valor_medio_24h, Decimal("200.00"))

    def test_fail_open_em_resposta_invalida(self):
        respostas = {
            "score fora de [0, 1]": resposta_json({"score": 7.5}),
            "sem score": resposta_json({}),
            "score booleano": resposta_json({"score": True}),
            "score em texto": resposta_json({"score": "0.97"}),
            "inteiro gigante": resposta_http("200 OK", b'{"score": 1' + b"0" * 400 + b"}"),
            "HTTP 500": resposta_http("500 Internal Server Error"),
        }
        for nome, bruto in respostas.items():
            with self.subTest(nome), ServidorCru(bruto) as servidor, self.assertLogs("bankmore_jev", "WARNING"):
                self.assertIsNone(score_do_fraud_ml(servidor.url, self.pix))
                self.assertEqual(len(servidor.requisicoes), 1)

    def test_fail_open_em_url_invalida(self):
        with self.assertLogs("bankmore_jev", "WARNING"):
            self.assertIsNone(score_do_fraud_ml("abc", self.pix))


if __name__ == "__main__":
    unittest.main()
