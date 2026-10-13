"""
Registro de modelos do fraud-ml: versões, fichas e estados, em arquivos.

Layout (dentro de ML_ARTIFACT_DIR/registro):
    registro.json             índice: estado de cada versão, produção, pilha de anteriores, histórico
    <versao>/model.joblib     o pipeline treinado
    <versao>/ficha.json       dados, código, critério, métricas e referência de drift
    <versao>/laudo-*.json     laudos do portão de promoção

Estados: candidato → sombra → producao → arquivado.
    - uma única versão em produção e no máximo uma em sombra;
    - promover exige um laudo APROVADO do portão, emitido contra a produção atual;
    - reverter() devolve a produção à versão anterior.

Escritas são atômicas (arquivo temporário + os.replace): o serviço lê o índice
sem nunca ver um arquivo pela metade. A CLI é o único escritor; não há trava
entre processos, então não rode duas CLIs ao mesmo tempo.

Uso:
    python registro.py listar
    python registro.py sombra <versao>
    python registro.py sem-sombra "motivo"
    python registro.py promover <versao> <laudo.json>
    python registro.py reverter "motivo"
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "/app/artifacts"))
VERSAO_VALIDA = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ESTADOS = ("candidato", "sombra", "producao", "arquivado")


class ErroDeRegistro(ValueError):
    """Transição inválida ou registro inconsistente."""


def saida_utf8() -> None:
    """CLIs imprimem acentos e setas: força UTF-8 também no console do Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gravar_json(caminho: Path, dados) -> None:
    """Escrita atômica: quem lê vê o arquivo antigo ou o novo, nunca a metade."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=caminho.name + ".", suffix=".tmp", dir=caminho.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


class Registro:
    def __init__(self, diretorio: Path | str | None = None, relogio=agora):
        self.dir = Path(diretorio) if diretorio else ARTIFACT_DIR / "registro"
        self.indice_path = self.dir / "registro.json"
        self._relogio = relogio

    # ----- leitura -----
    def existe(self) -> bool:
        return self.indice_path.exists()

    def indice(self) -> dict:
        if not self.existe():
            return {"versoes": {}, "producao": None, "sombra": None, "anteriores": [], "historico": []}
        return json.loads(self.indice_path.read_text(encoding="utf-8"))

    def producao(self) -> str | None:
        return self.indice()["producao"]

    def sombra(self) -> str | None:
        return self.indice()["sombra"]

    def _validar(self, versao: str) -> str:
        if not isinstance(versao, str) or not VERSAO_VALIDA.fullmatch(versao):
            raise ErroDeRegistro(f"versão inválida: {versao!r} (use minúsculas, números, '.', '_' e '-')")
        return versao

    def estado_de(self, versao: str) -> str:
        versoes = self.indice()["versoes"]
        if versao not in versoes:
            raise ErroDeRegistro(f"versão {versao} não está no registro")
        return versoes[versao]["estado"]

    def ficha(self, versao: str) -> dict:
        return json.loads((self.dir / self._validar(versao) / "ficha.json").read_text(encoding="utf-8"))

    def caminho_modelo(self, versao: str) -> Path:
        return self.dir / self._validar(versao) / "model.joblib"

    def carregar(self, versao: str):
        import joblib  # só quem carrega modelo precisa do joblib
        return joblib.load(self.caminho_modelo(versao))

    # ----- escrita -----
    def registrar(self, versao: str, pipeline, ficha: dict) -> None:
        """Nova versão como candidata. A versão é imutável: não sobrescreve."""
        self._validar(versao)
        indice = self.indice()
        if versao in indice["versoes"] or (self.dir / versao).exists():
            raise ErroDeRegistro(f"versão {versao} já existe; versões são imutáveis")
        import joblib
        destino = self.dir / versao
        temporario = self.dir / f".{versao}.tmp"
        shutil.rmtree(temporario, ignore_errors=True)
        temporario.mkdir(parents=True)
        joblib.dump(pipeline, temporario / "model.joblib")
        gravar_json(temporario / "ficha.json", {**ficha, "versao": versao})
        os.replace(temporario, destino)
        indice["versoes"][versao] = {"estado": "candidato", "registrado_em": self._relogio()}
        self._evento(indice, "registrado", versao, None, "candidato", ficha.get("motivo", "retreino"))
        gravar_json(self.indice_path, indice)

    def colocar_em_sombra(self, versao: str, motivo: str = "") -> None:
        """Pontua as mesmas transações da produção (depois da decisão), registra onde discorda, não decide."""
        indice = self.indice()
        self._exigir(indice, versao, ("candidato",))
        anterior = indice["sombra"]
        if anterior:
            indice["versoes"][anterior]["estado"] = "candidato"
            self._evento(indice, "saiu_da_sombra", anterior, "sombra", "candidato", f"substituída por {versao}")
        indice["versoes"][versao]["estado"] = "sombra"
        indice["sombra"] = versao
        self._evento(indice, "em_sombra", versao, "candidato", "sombra", motivo)
        gravar_json(self.indice_path, indice)

    def tirar_da_sombra(self, motivo: str) -> str | None:
        """A versão em sombra volta a candidata (ex.: sombra quebrada ou cara demais)."""
        indice = self.indice()
        versao = indice["sombra"]
        if versao is None:
            return None
        indice["versoes"][versao]["estado"] = "candidato"
        indice["sombra"] = None
        self._evento(indice, "saiu_da_sombra", versao, "sombra", "candidato", motivo)
        gravar_json(self.indice_path, indice)
        return versao

    def promover(self, versao: str, laudo: dict | None, motivo: str = "") -> None:
        """Candidato ou sombra vira produção. Exige laudo aprovado contra a produção atual,
        emitido com a mesma régua registrada na ficha do candidato.

        A única exceção é a primeira versão, quando ainda não há produção. O laudo
        não é assinado: a garantia é de processo (a CLI), não criptográfica.
        """
        indice = self.indice()
        de = self._exigir(indice, versao, ("candidato", "sombra"))
        atual = indice["producao"]
        if atual is not None:
            if not laudo or not laudo.get("aprovado"):
                raise ErroDeRegistro("promoção exige um laudo aprovado do portão")
            if laudo.get("candidato") != versao or laudo.get("producao") != atual:
                raise ErroDeRegistro(
                    f"laudo é de {laudo.get('candidato')} contra {laudo.get('producao')}; "
                    f"a promoção pedida é de {versao} contra {atual}. Rode o portão de novo."
                )
            regua_laudo = (laudo.get("criterio") or {}).get("hash")
            regua_ficha = self.ficha(versao).get("hash_criterio")
            if regua_laudo != regua_ficha:
                raise ErroDeRegistro("o laudo foi emitido com uma régua diferente da registrada na ficha do candidato")
            indice["versoes"][atual]["estado"] = "arquivado"
            indice["anteriores"].append(atual)
            self._evento(indice, "arquivado", atual, "producao", "arquivado", f"substituída por {versao}")
        indice["versoes"][versao]["estado"] = "producao"
        indice["producao"] = versao
        if indice["sombra"] == versao:
            indice["sombra"] = None
        self._evento(indice, "promovido", versao, de, "producao", motivo or ("primeira versão" if atual is None else "laudo aprovado"))
        gravar_json(self.indice_path, indice)

    def reverter(self, motivo: str) -> str:
        """Volta a produção para a versão anterior. Devolve a versão que voltou."""
        if not motivo.strip():
            raise ErroDeRegistro("reverter exige um motivo (ele vai para o histórico)")
        indice = self.indice()
        if not indice["anteriores"]:
            raise ErroDeRegistro("não há versão anterior para voltar")
        atual = indice["producao"]
        anterior = indice["anteriores"].pop()
        indice["versoes"][atual]["estado"] = "arquivado"
        indice["versoes"][anterior]["estado"] = "producao"
        indice["producao"] = anterior
        self._evento(indice, "revertido", atual, "producao", "arquivado", motivo)
        self._evento(indice, "restaurado", anterior, "arquivado", "producao", motivo)
        gravar_json(self.indice_path, indice)
        return anterior

    def gravar_laudo(self, laudo: dict) -> Path:
        carimbo = self._relogio().replace(":", "").replace("-", "").replace("+", "")
        caminho = self.dir / self._validar(laudo["candidato"]) / f"laudo-{carimbo}.json"
        gravar_json(caminho, laudo)
        return caminho

    # ----- internos -----
    def _exigir(self, indice: dict, versao: str, estados: tuple) -> str:
        if versao not in indice["versoes"]:
            raise ErroDeRegistro(f"versão {versao} não está no registro")
        estado = indice["versoes"][versao]["estado"]
        if estado not in estados:
            raise ErroDeRegistro(f"{versao} está em {estado}; esta operação exige {' ou '.join(estados)}")
        return estado

    def _evento(self, indice: dict, evento: str, versao: str, de, para, motivo: str) -> None:
        indice["historico"].append({
            "quando": self._relogio(), "evento": evento, "versao": versao,
            "de": de, "para": para, "motivo": motivo,
        })


def _cli(argv: list[str]) -> int:
    saida_utf8()
    reg = Registro()
    if not argv or argv[0] == "listar":
        indice = reg.indice()
        print(f"produção: {indice['producao']}  |  sombra: {indice['sombra']}  |  anteriores: {indice['anteriores']}")
        for versao, info in indice["versoes"].items():
            print(f"  {versao:<24} {info['estado']:<10} registrado em {info['registrado_em']}")
        for e in indice["historico"][-8:]:
            print(f"  · {e['quando']} {e['evento']:<14} {e['versao']:<20} {e['motivo']}")
        return 0
    try:
        if argv[0] == "sombra" and len(argv) == 2:
            reg.colocar_em_sombra(argv[1], "CLI")
        elif argv[0] == "sem-sombra" and len(argv) == 2:
            print(f"saiu da sombra: {reg.tirar_da_sombra(argv[1])}")
        elif argv[0] == "promover" and len(argv) == 3:
            reg.promover(argv[1], json.loads(Path(argv[2]).read_text(encoding="utf-8")), "CLI com laudo")
        elif argv[0] == "reverter" and len(argv) == 2:
            print(f"produção voltou para {reg.reverter(argv[1])}")
        else:
            print(__doc__)
            return 2
    except ErroDeRegistro as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    return _cli(["listar"])


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
