"""python -m bankmore_jev: roda a demonstração do antifraude Pix com o Jev."""
from __future__ import annotations

import argparse
import logging
import sys

from .api import PORTA_PADRAO, servir
from .demo import executar


def _url_http(valor: str) -> str:
    if not valor.startswith(("http://", "https://")):
        raise argparse.ArgumentTypeError("use uma URL http:// ou https://, ex.: http://localhost:5003")
    return valor


def _porta(valor: str) -> int:
    try:
        porta = int(valor)
    except ValueError:
        porta = -1
    if not 1 <= porta <= 65535:
        raise argparse.ArgumentTypeError("use uma porta entre 1 e 65535")
    return porta


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
    parser.add_argument("--api", action="store_true", help="sobe a API da tela /ops/jev do frontend em vez de imprimir a tabela")
    parser.add_argument("--porta", type=_porta, default=PORTA_PADRAO, help=f"porta da API (padrão {PORTA_PADRAO})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="aviso: %(message)s")
    return servir(args) if args.api else executar(args)


if __name__ == "__main__":
    sys.exit(main())
