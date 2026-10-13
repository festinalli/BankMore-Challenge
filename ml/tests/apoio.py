"""Apoio dos testes: modelos pequenos e registros em pastas temporárias."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

from registro import Registro  # noqa: E402
from retreinar import CRITERIO_PATH, executar  # noqa: E402

N_PEQUENO = 4000


def pasta_temporaria(caso) -> Path:
    pasta = tempfile.TemporaryDirectory(prefix="bankmore-ml-teste-")
    caso.addCleanup(pasta.cleanup)
    return Path(pasta.name)


def treinar(registro: Registro, versao: str, cenario: str = "base", seed: int = 42,
            n: int = N_PEQUENO, criterio_path: Path = CRITERIO_PATH) -> dict:
    return executar(versao, cenario=cenario, seed=seed, n=n, fracao_fraude=0.02,
                    registro=registro, motivo="teste", verboso=False, criterio_path=criterio_path)


def criterio(pasta: Path, nome: str, **mudancas) -> Path:
    """Cópia do critério real com mudanças (avaliação pequena, para o teste ser rápido)."""
    dados = json.loads(CRITERIO_PATH.read_text(encoding="utf-8"))
    dados["avaliacao"] = {**dados["avaliacao"], "n": 6000}
    dados.update(mudancas)
    caminho = pasta / nome
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho
