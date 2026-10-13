import unittest

from tests import apoio  # noqa: F401  (ajusta o sys.path)

from dados import CENARIOS, descrever, gerar, hash_dados


class DadosTest(unittest.TestCase):
    def test_mesmos_argumentos_mesmo_dataset(self):
        a, b = gerar(3000, 0.02, 1, "base"), gerar(3000, 0.02, 1, "base")
        self.assertEqual(hash_dados(a), hash_dados(b))
        self.assertNotEqual(hash_dados(a), hash_dados(gerar(3000, 0.02, 2, "base")))

    def test_hash_muda_com_qualquer_valor(self):
        df = gerar(1000, 0.02, 1, "base")
        alterado = df.copy()
        alterado.loc[0, "valor"] += 0.01
        self.assertNotEqual(hash_dados(df), hash_dados(alterado))

    def test_base_e_o_dataset_do_treino_original(self):
        # Hash conferido contra o train.py anterior (commit af560f6): o cenário base com
        # seed 42 gera o mesmo dataset (verificado byte a byte no Windows). O hash
        # arredonda a 6 casas para valer igual no Linux.
        self.assertEqual(hash_dados(gerar(2000, 0.02, 42, "base")),
                         "sha256:3b86e15593c7c4b86638dd295aee6f32f95f50b6396fde77a22345b0ac47705c")

    def test_avaliacao_usa_um_fluxo_que_o_treino_nao_reproduz(self):
        seed = 20261013
        avaliacao = hash_dados(gerar(4000, 0.02, seed, "nova_fraude", avaliacao=True))
        self.assertEqual(avaliacao, hash_dados(gerar(4000, 0.02, seed, "nova_fraude", avaliacao=True)))
        for s in range(seed - 2, seed + 3):
            with self.subTest(seed_de_treino=s):
                self.assertNotEqual(avaliacao, hash_dados(gerar(4000, 0.02, s, "nova_fraude")))
        mistura = gerar(8000, 0.02, seed - 1, "base+nova_fraude")
        conjunto = gerar(4000, 0.02, seed, "nova_fraude", avaliacao=True)
        comuns = mistura.merge(conjunto, how="inner", on=list(conjunto.columns))
        self.assertEqual(len(comuns), 0)

    def test_nova_fraude_traz_o_padrao_f6_e_valores_maiores(self):
        base, novo = gerar(20000, 0.02, 3, "base"), gerar(20000, 0.02, 3, "nova_fraude")
        self.assertAlmostEqual(novo["is_fraude"].mean(), 0.02, places=3)
        fraudes = novo[novo["is_fraude"] == 1]
        razao = fraudes["valor"] / fraudes["valor_medio_cpf_24h"]
        f6 = fraudes[(razao.between(4, 8)) & fraudes["count_tx_cpf_1h"].between(2, 4) & fraudes["hora_do_dia"].between(9, 18)]
        self.assertGreaterEqual(len(f6) / len(fraudes), 0.35)
        legitimos = lambda df: df[df["is_fraude"] == 0]["valor"].median()  # noqa: E731
        self.assertGreater(legitimos(novo), 1.5 * legitimos(base))

    def test_mistura_de_cenarios(self):
        df = gerar(5001, 0.02, 9, "base+nova_fraude")
        self.assertEqual(len(df), 5001)
        self.assertEqual(hash_dados(df), hash_dados(gerar(5001, 0.02, 9, "base+nova_fraude")))
        self.assertIn("mistura", descrever("base+nova_fraude"))

    def test_cenario_desconhecido(self):
        for cenario in ("marte", "base+marte"):
            with self.subTest(cenario=cenario), self.assertRaises(ValueError):
                gerar(100, 0.02, 1, cenario)
        self.assertEqual(set(CENARIOS), {"base", "nova_fraude"})


if __name__ == "__main__":
    unittest.main()
