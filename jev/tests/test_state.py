import json
import time
import unittest
from decimal import Decimal

from bankmore_jev.state import MAX_TEXTO, Pix, faixa_absoluta, faixa_de_valor, idade_da_chave, mascarar, montar_estado, periodo


def pix(**overrides):
    dados = {
        "valor": Decimal("1800.00"),
        "hora_local": 19,
        "tipo_iniciacao": "MANUAL",
        "count_tx_1h": 1,
        "valor_habitual": Decimal("2500.00"),
        "primeiro_pix_para_destino": True,
        "chave_destino_idade_dias": 2,
        "dispositivo_novo": False,
        "motivo_informado": "Meu filho trocou de número",
        "historico": "Paga contas",
    }
    dados.update(overrides)
    return Pix(**dados)


class MascaramentoTest(unittest.TestCase):
    def test_remove_dados_pessoais(self):
        casos = {
            "CPF 123.456.789-09 do meu filho": "CPF [número] do meu filho",
            "cpf 123,456,789-09": "cpf [número]",
            "cpf 123_456_789_09": "cpf [número]",
            "cpf 123/456/789/09": "cpf [número]",
            "CNPJ 12.345.678/0001-90 da loja": "CNPJ [número] da loja",
            "liga no (11) 98765-4321 agora": "liga no [número] agora",
            "manda para +55 11 987654321": "manda para [número]",
            "cartão 4111 1111 1111 1111": "cartão [número]",
            "meu email é fulano.silva@exemplo.com.br": "meu email é [email]",
            "vendedor @loja.iphones.baratos no Insta": "vendedor [perfil] no Insta",
            "conta 12345678 agência 0001": "conta [número] agência 0001",
            "ag 1234 cc 12345-6 Itaú": "ag 1234 cc [conta] Itaú",
            "chave 7f3c2a1b-9d4e-4f6a-8b2c-1a2b3c4d5e6f": "chave [chave]",
            "chave 0f8fad5bd9cb469fa16570867728950e": "chave [chave]",
            "cpf １２３.４５６.７８９-０９": "cpf [número]",
            "CEP 01310-100": "CEP [número]",
            "RG 12.345.678-9": "RG [número]",
            "CNPJ 12.ABC.345/01DE-35 da loja": "CNPJ [número] da loja",
            "CNPJ 12ABC34501DE35": "CNPJ [número]",
            "tel (11) 98765\u20134321": "tel [número]",
            "tel 11 98765\u22124321": "tel [número]",
            "cpf 123\u2010456\u2010789\u201009": "cpf [número]",
            "cpf 123\u2011456\u2011789\u201109": "cpf [número]",
            "cpf 123\u00b7456\u00b7789-09": "cpf [número]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(mascarar(texto), esperado)

    def test_mantem_numeros_curtos_valores_e_datas(self):
        for texto in ("aluguel de R$ 2.500 do apto 302", "R$ 150.000,00 do carro", "vence em 10/10/2026"):
            with self.subTest(texto=texto):
                self.assertEqual(mascarar(texto), texto)

    def test_nao_mascara_palavras_em_maiusculas(self):
        self.assertEqual(mascarar("PAGAMENTOURGENTE DE HOJE"), "PAGAMENTOURGENTE DE HOJE")

    def test_custo_limitado_em_texto_enorme(self):
        for texto in ("a" * 100000, "a." * 50000, "1" * 100000):
            with self.subTest(tamanho=len(texto)):
                inicio = time.perf_counter()
                self.assertLessEqual(len(mascarar(texto)), MAX_TEXTO)
                self.assertLess(time.perf_counter() - inicio, 0.5)

    def test_remove_caracteres_de_controle_e_surrogate_solto(self):
        self.assertEqual(mascarar("pagar‮ agora\x1b[31m\ud800 ok"), "pagar agora [31m ok")

    def test_limita_o_tamanho_e_os_espacos(self):
        self.assertEqual(len(mascarar("a " * 1000)), MAX_TEXTO)
        self.assertEqual(mascarar("  muito   espaço \n aqui "), "muito espaço aqui")


class EstadoTest(unittest.TestCase):
    def test_numeros_viram_fatos(self):
        self.assertEqual([periodo(h) for h in (0, 5, 6, 11, 12, 17, 18, 23)],
                         ["madrugada", "madrugada", "manhã", "manhã", "tarde", "tarde", "noite", "noite"])
        self.assertEqual(faixa_de_valor(Decimal("100"), Decimal("100")), "dentro do habitual do cliente")
        self.assertEqual(faixa_de_valor(Decimal("300"), Decimal("100")), "acima do habitual do cliente")
        self.assertEqual(faixa_de_valor(Decimal("301"), Decimal("100")), "muito acima do habitual do cliente")
        self.assertEqual(faixa_de_valor(Decimal("50"), Decimal("0")), "cliente sem histórico de valores")
        self.assertEqual([idade_da_chave(d) for d in (0, 6, 7, 89, 90)], [
            "cadastrada há menos de 7 dias", "cadastrada há menos de 7 dias",
            "cadastrada nos últimos 3 meses", "cadastrada nos últimos 3 meses",
            "cadastrada há mais de 3 meses",
        ])
        self.assertEqual([faixa_absoluta(Decimal(v)) for v in ("0.01", "200", "200.01", "1000", "5000", "20000", "20000.01")], [
            "até R$ 200", "até R$ 200", "de R$ 200 a R$ 1 mil", "de R$ 200 a R$ 1 mil",
            "de R$ 1 mil a R$ 5 mil", "de R$ 5 mil a R$ 20 mil", "acima de R$ 20 mil",
        ])

    def test_estado_nao_tem_dados_pessoais_nem_valor_exato(self):
        estado = montar_estado(pix(motivo_informado="pix pro CPF 123.456.789-09, tel 11 98765-4321, chave 7f3c2a1b-9d4e-4f6a-8b2c-1a2b3c4d5e6f"))
        texto = json.dumps(estado, ensure_ascii=False)
        for dado in ("123.456.789-09", "98765-4321", "7f3c2a1b", "1.800", "1800"):
            with self.subTest(dado=dado):
                self.assertNotIn(dado, texto)
        self.assertEqual(estado["pagamento"]["valor"], "de R$ 1 mil a R$ 5 mil")
        self.assertEqual(estado["pagamento"]["chave_do_destinatario"], "cadastrada há menos de 7 dias")

    def test_texto_vazio_vira_marcador(self):
        estado = montar_estado(pix(motivo_informado="", historico=""))
        self.assertEqual(estado["motivo_informado_pelo_cliente"], "(não informado)")
        self.assertEqual(estado["historico_do_cliente"], "(sem histórico)")

    def test_rejeita_dados_impossiveis(self):
        for invalido in ({"hora_local": 24}, {"valor": Decimal("0")}, {"count_tx_1h": -1}, {"valor_medio_24h": Decimal("-1")}):
            with self.subTest(invalido=invalido), self.assertRaises(ValueError):
                pix(**invalido)


if __name__ == "__main__":
    unittest.main()
