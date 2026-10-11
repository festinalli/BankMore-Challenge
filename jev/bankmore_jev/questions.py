"""Perguntas feitas ao Jev em uma única chamada (padrão fan-out da TypeSafe).

As instruções estão em inglês: segundo a página Models da TypeSafe, é o idioma
principal de treino, e outros idiomas "são tratados, mas não igualmente bem".
O estado segue em português, como o cliente escreveu, e é justamente a parte
mais fraca: calibre os limiares com mensagens reais.

O Jev tende a favorecer a primeira opção de uma Choice (jev-1.13). Por padrão
`falso_parente` vem primeiro, o que empurra para cautela e também pode inflar o
resultado da demonstração. A TypeSafe recomenda reordenar e conferir se a
resposta se mantém: `perguntas(nenhum_primeiro=True)` (--nenhum-primeiro na CLI).
"""
from __future__ import annotations

import copy

GOLPE = "golpe"
NENHUM = "nenhum"
SINAIS = ("pressao_de_terceiro", "instruido_por_terceiro")

_GOLPES = {
    "falso_parente": "A relative or friend supposedly changed phone number or urgently asks the payer for money",
    "falsa_central": "Someone posing as the bank, a security team or an authority tells the payer to move money to a 'safe' account",
    "falso_vendedor": "Advance payment to an unknown seller for a deal that is too good to be true",
    "outro_golpe": "Signs of a scam that does not fit the patterns above (fake investment, fake job, extortion, fake prize)",
}
_NENHUM = "An ordinary payment with no sign of a scam"

OPCOES_GOLPE = frozenset([*_GOLPES, NENHUM])


def perguntas(nenhum_primeiro: bool = False) -> dict:
    """As três perguntas da chamada; a ordem das opções da Choice é configurável."""
    criterios = {NENHUM: _NENHUM, **_GOLPES} if nenhum_primeiro else {**_GOLPES, NENHUM: _NENHUM}
    return {
        GOLPE: {
            "type": "choice",
            "instructions": (
                "Based on `motivo_informado_pelo_cliente`, `historico_do_cliente` and `pagamento`, "
                "which scam pattern does this Pix payment match?"
            ),
            "criteria": criterios,
        },
        "pressao_de_terceiro": {
            "type": "noul",
            "instructions": "The payer is acting under urgency, pressure or secrecy imposed by someone else.",
        },
        "instruido_por_terceiro": {
            "type": "noul",
            "instructions": (
                "The payment was instructed by another person (a call, a message, a chat) "
                "rather than being the payer's own initiative."
            ),
        },
    }


QUESTIONS = perguntas()


def copia(questions: dict) -> dict:
    return copy.deepcopy(questions)
