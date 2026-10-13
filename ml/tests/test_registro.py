import json
import unittest

from tests.apoio import pasta_temporaria

from registro import ErroDeRegistro, Registro


def laudo(candidato, producao, aprovado=True):
    return {"candidato": candidato, "producao": producao, "aprovado": aprovado}


class RegistroTest(unittest.TestCase):
    def setUp(self):
        self.reg = Registro(pasta_temporaria(self) / "registro")
        for versao in ("v1", "v2", "v3"):
            self.reg.registrar(versao, {"modelo": versao}, {"limiar": 0.5})

    def test_registra_como_candidato_e_guarda_ficha_e_modelo(self):
        self.assertEqual(self.reg.estado_de("v1"), "candidato")
        self.assertEqual(self.reg.ficha("v1")["versao"], "v1")
        self.assertEqual(self.reg.carregar("v1"), {"modelo": "v1"})
        self.assertEqual(self.reg.indice()["historico"][0]["evento"], "registrado")

    def test_versoes_sao_imutaveis_e_validadas(self):
        with self.assertRaises(ErroDeRegistro):
            self.reg.registrar("v1", {}, {})
        for invalida in ("V1", "../fora", "", "a" * 65, "com espaço", "v1\n"):
            with self.subTest(versao=invalida), self.assertRaises(ErroDeRegistro):
                self.reg.registrar(invalida, {}, {})

    def test_primeira_promocao_sem_laudo_depois_so_com_laudo_valido(self):
        self.reg.promover("v1", None)
        self.assertEqual(self.reg.producao(), "v1")
        casos = {
            "sem laudo": None,
            "reprovado": laudo("v2", "v1", aprovado=False),
            "de outro candidato": laudo("v3", "v1"),
            "contra outra produção": laudo("v2", "v0"),
        }
        for nome, l in casos.items():
            with self.subTest(nome), self.assertRaises(ErroDeRegistro):
                self.reg.promover("v2", l)
        self.reg.promover("v2", laudo("v2", "v1"))
        self.assertEqual(self.reg.producao(), "v2")
        self.assertEqual(self.reg.estado_de("v1"), "arquivado")
        self.assertEqual(self.reg.indice()["anteriores"], ["v1"])

    def test_leituras_validam_o_nome(self):
        for invalida in ("../fora", "v1\n"):
            with self.subTest(versao=invalida), self.assertRaises(ErroDeRegistro):
                self.reg.ficha(invalida)

    def test_laudo_com_outra_regua_nao_promove(self):
        reg = Registro(pasta_temporaria(self) / "outro")
        reg.registrar("a", {}, {"limiar": 0.5, "hash_criterio": "sha256:regua-do-treino"})
        reg.registrar("b", {}, {"limiar": 0.5, "hash_criterio": "sha256:regua-do-treino"})
        reg.promover("a", None)
        outra = {**laudo("b", "a"), "criterio": {"hash": "sha256:outra-regua"}}
        with self.assertRaises(ErroDeRegistro):
            reg.promover("b", outra)
        reg.promover("b", {**laudo("b", "a"), "criterio": {"hash": "sha256:regua-do-treino"}})
        self.assertEqual(reg.producao(), "b")

    def test_tirar_da_sombra(self):
        self.reg.promover("v1", None)
        self.assertIsNone(self.reg.tirar_da_sombra("nada em sombra"))
        self.reg.colocar_em_sombra("v2")
        self.assertEqual(self.reg.tirar_da_sombra("sombra quebrada"), "v2")
        self.assertIsNone(self.reg.sombra())
        self.assertEqual(self.reg.estado_de("v2"), "candidato")

    def test_uma_sombra_por_vez(self):
        self.reg.promover("v1", None)
        self.reg.colocar_em_sombra("v2")
        self.reg.colocar_em_sombra("v3")
        self.assertEqual(self.reg.sombra(), "v3")
        self.assertEqual(self.reg.estado_de("v2"), "candidato")
        with self.assertRaises(ErroDeRegistro):
            self.reg.colocar_em_sombra("v1")  # produção não vai para a sombra
        self.reg.promover("v3", laudo("v3", "v1"))
        self.assertIsNone(self.reg.sombra())

    def test_reverter_volta_para_a_anterior_com_motivo(self):
        self.reg.promover("v1", None)
        with self.assertRaises(ErroDeRegistro):
            self.reg.reverter("sem anterior")
        self.reg.promover("v2", laudo("v2", "v1"))
        with self.assertRaises(ErroDeRegistro):
            self.reg.reverter("   ")
        self.assertEqual(self.reg.reverter("incidente"), "v1")
        self.assertEqual(self.reg.producao(), "v1")
        self.assertEqual(self.reg.estado_de("v2"), "arquivado")
        ultimos = [(e["evento"], e["versao"], e["motivo"]) for e in self.reg.indice()["historico"][-2:]]
        self.assertEqual(ultimos, [("revertido", "v2", "incidente"), ("restaurado", "v1", "incidente")])

    def test_indice_sempre_valido_e_sem_temporarios(self):
        self.reg.promover("v1", None)
        self.reg.colocar_em_sombra("v2")
        json.loads(self.reg.indice_path.read_text(encoding="utf-8"))
        sobras = [p.name for p in self.reg.dir.iterdir() if p.name.endswith(".tmp") or p.name.startswith(".")]
        self.assertEqual(sobras, [])

    def test_laudo_gravado_na_pasta_do_candidato(self):
        caminho = self.reg.gravar_laudo({"candidato": "v2", "aprovado": False})
        self.assertEqual(caminho.parent.name, "v2")
        self.assertFalse(json.loads(caminho.read_text(encoding="utf-8"))["aprovado"])


if __name__ == "__main__":
    unittest.main()
