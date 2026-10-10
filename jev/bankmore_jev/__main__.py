"""python -m bankmore_jev: roda a demonstração do antifraude Pix com o Jev."""
from __future__ import annotations

import argparse
import logging
import sys

from .demo import executar


def _url_http(valor: str) -> str:
    if not valor.startswith(("http://", "https://")):
        raise argparse.ArgumentTypeError("use uma URL http:// ou https://, ex.: http://localhost:5003")
    return valor


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):  # antes do argparse, para o --help também sair em UTF-8
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m bankmore_jev",
        description="Antifraude Pix do BankMore com o Jev: o XGBoost lê os números, o Jev lê o contexto, o código decide.",
    )
    parser.add_argument("--offline", action="store_true", help="usa respostas SIMULADAS do Jev (não precisa de chave)")
    parser.add_argument("--ml-url", type=_url_http, help="URL do fraud-ml (ex.: http://localhost:5003) para usar o score real do XGBoost")
    parser.add_argument("--cenario", type=int, help="roda só o cenário com este número")
    parser.add_argument("--nenhum-primeiro", action="store_true", help="põe 'nenhum' como primeira opção da Choice, para medir o viés de ordem")
    parser.add_argument("--json", action="store_true", help="uma linha JSON por cenário")
    parser.add_argument("--sem-cor", action="store_true", help="desliga as cores do terminal")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="aviso: %(message)s")
    return executar(args)


if __name__ == "__main__":
    sys.exit(main())
