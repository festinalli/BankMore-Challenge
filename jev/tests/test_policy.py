import itertools
import unittest

from bankmore_jev.client import ChoiceAnswer, JevResult
from bankmore_jev.policy import Acao, decidir
from bankmore_jev.questions import GOLPE


def jev(choice="nenhum", confidence=0.9, pressao=0.0, instruido=0.0):
    return JevResult(
        choices={GOLPE: ChoiceAnswer(choice, confidence, {})},
        nouls={"pressao_de_terceiro": pressao, "instruido_por_terceiro": instruido},
        model="teste",
        latency_ms=1.0,
    )


def parcial(choice=None, confidence=0.9, **nouls):
    choices = {} if choice is None else {GOLPE: ChoiceAnswer(choice, confidence, {})}
    return JevResult(choices=choices, nouls=nouls, model="teste", latency_ms=1.0)


class PolicyTest(unittest.TestCase):
    def test_tabela_de_decisoes(self):
        casos = [
            ("pagamento comum", 0.02, jev(), Acao.APROVAR, ()),
            ("XGBoost no limiar recusa", 0.95, jev(), Acao.RECUSAR, ("XGBOOST_SCORE_ALTO",)),
            ("golpe com confiança alta retém", 0.08, jev("falso_parente", 0.91), Acao.RETER_PARA_ANALISE, ("GOLPE_FALSO_PARENTE",)),
            ("golpe com confiança média confirma", 0.08, jev("falso_vendedor", 0.70), Acao.CONFIRMAR_COM_CLIENTE, ("GOLPE_FALSO_VENDEDOR",)),
            ("confiança exatamente 0,85 já retém", 0.1, jev("falsa_central", 0.85), Acao.RETER_PARA_ANALISE, ("GOLPE_FALSA_CENTRAL",)),
            ("golpe fora dos padrões também conta", 0.1, jev("outro_golpe", 0.9), Acao.RETER_PARA_ANALISE, ("GOLPE_OUTRO_GOLPE",)),
            (
                "golpe com confiança média e sinal de terceiro retém",
                0.1,
                jev("falso_parente", 0.72, pressao=0.88),
                Acao.RETER_PARA_ANALISE,
                ("GOLPE_FALSO_PARENTE", "SINAL_PRESSAO_DE_TERCEIRO"),
            ),
            ("dúvida do Jev pede confirmação", 0.1, jev("nenhum", 0.59), Acao.CONFIRMAR_COM_CLIENTE, ("JEV_INCERTO",)),
            ("sinal de terceiro sem golpe confirma", 0.1, jev(pressao=0.8), Acao.CONFIRMAR_COM_CLIENTE, ("SINAL_PRESSAO_DE_TERCEIRO",)),
            ("sinal logo abaixo do limiar não conta", 0.1, jev(pressao=0.79), Acao.APROVAR, ()),
            (
                "golpe e sinais aparecem juntos nos motivos",
                0.1,
                jev("falso_parente", 0.9, pressao=0.95, instruido=0.9),
                Acao.RETER_PARA_ANALISE,
                ("GOLPE_FALSO_PARENTE", "SINAL_PRESSAO_DE_TERCEIRO", "SINAL_INSTRUIDO_POR_TERCEIRO"),
            ),
        ]
        for nome, score, resposta, acao, motivos in casos:
            with self.subTest(nome):
                decisao = decidir(score, resposta)
                self.assertEqual(decisao.acao, acao)
                self.assertEqual(decisao.motivos, motivos)

    def test_jev_nunca_libera_o_que_o_xgboost_barrou(self):
        respostas = [
            jev(choice, confidence, pressao, instruido)
            for choice, confidence, pressao, instruido in itertools.product(
                ["nenhum", "falso_parente", "falsa_central", "falso_vendedor", "outro_golpe", "rotulo_inventado"],
                [0.0, 0.59, 0.6, 0.84, 0.85, 1.0],
                [0.0, 0.8, 1.0],
                [0.0, 0.8, 1.0],
            )
        ] + [None, parcial(), parcial("nenhum", 1.0), parcial(pressao_de_terceiro=0.0)]
        for score in [None, 0.0, 0.5, 0.95, 1.0]:
            so_xgboost = decidir(score, None).acao
            for resposta in respostas:
                with self.subTest(score=score, resposta=resposta):
                    self.assertGreaterEqual(decidir(score, resposta).acao, so_xgboost)

    def test_fail_open_quando_o_jev_cai(self):
        decisao = decidir(0.1, None)
        self.assertEqual(decisao.acao, Acao.APROVAR)
        self.assertEqual(decisao.motivos, ("JEV_INDISPONIVEL",))

    def test_fail_open_quando_tudo_cai(self):
        decisao = decidir(None, None)
        self.assertEqual(decisao.acao, Acao.APROVAR)
        self.assertEqual(decisao.motivos, ("XGBOOST_INDISPONIVEL", "JEV_INDISPONIVEL"))

    def test_resposta_parcial_aproveita_o_que_veio(self):
        casos = [
            ("sem nenhuma resposta", parcial(), Acao.APROVAR, ("JEV_RESPOSTA_INCOMPLETA",)),
            ("sem os sinais", parcial("falso_parente", 0.99), Acao.RETER_PARA_ANALISE, ("JEV_RESPOSTA_INCOMPLETA", "GOLPE_FALSO_PARENTE")),
            (
                "sem a choice",
                parcial(pressao_de_terceiro=1.0, instruido_por_terceiro=1.0),
                Acao.CONFIRMAR_COM_CLIENTE,
                ("JEV_RESPOSTA_INCOMPLETA", "SINAL_PRESSAO_DE_TERCEIRO", "SINAL_INSTRUIDO_POR_TERCEIRO"),
            ),
            ("só um sinal, baixo", parcial(pressao_de_terceiro=0.1), Acao.APROVAR, ("JEV_RESPOSTA_INCOMPLETA",)),
        ]
        for nome, resposta, acao, motivos in casos:
            with self.subTest(nome):
                decisao = decidir(0.1, resposta)
                self.assertEqual(decisao.acao, acao)
                self.assertEqual(decisao.motivos, motivos)

    def test_escolha_fora_das_opcoes_nao_vira_motivo(self):
        resposta = jev("\x1b[31mGOLPE_INVENTADO\nlinha", 0.99)
        decisao = decidir(0.1, resposta)
        self.assertEqual(decisao.acao, Acao.APROVAR)
        self.assertEqual(decisao.motivos, ("JEV_ESCOLHA_DESCONHECIDA", "JEV_RESPOSTA_INCOMPLETA"))


if __name__ == "__main__":
    unittest.main()
