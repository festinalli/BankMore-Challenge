"""A política: o XGBoost lê os números, o Jev lê o contexto, o código decide.

Regras:
1. O XGBoost continua soberano nos números (limiar 0,95, ADR 0018).
2. O Jev só pode AUMENTAR a cautela, nunca liberar o que o XGBoost barrou.
   O texto que ele lê é digitado pelo cliente, ou ditado pelo golpista, e um
   texto manipulado pode mudar a resposta (documentação da TypeSafe). Se o
   golpista enganar o Jev, o pior caso é voltar ao que o XGBoost faria sozinho.
3. A confiança decide se o código age: abaixo de 0,6 vira dúvida; a partir de
   0,85, o código age sozinho. Os números vêm do padrão confidence routing da
   TypeSafe (lá, "> 0,85"; aqui o empate retém, por cautela).
4. Golpe identificado com sinal forte de terceiro também retém: confirmar com o
   cliente é um controle fraco quando o golpista está orientando a vítima.
5. Fail-open, como o resto do antifraude do BankMore (ADR 0004 e 0018): se o
   Jev cair ou responder fora do contrato, vale a decisão do XGBoost. Resposta
   parcial é aproveitada no que veio, porque só pode acrescentar cautela.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .client import JevResult
from .questions import GOLPE, NENHUM, OPCOES_GOLPE, SINAIS


class Acao(IntEnum):
    """Ações em ordem crescente de atrito para o cliente."""

    APROVAR = 0
    CONFIRMAR_COM_CLIENTE = 1  # alerta de golpe na tela e confirmação explícita
    RETER_PARA_ANALISE = 2  # o PSP pagador segura antes de enviar ao SPI e aciona análise humana
    RECUSAR = 3


@dataclass(frozen=True)
class Limiares:
    xgboost_recusa: float = 0.95
    confianca_minima: float = 0.60
    confianca_alta: float = 0.85
    sinal: float = 0.80


@dataclass(frozen=True)
class Decisao:
    acao: Acao
    motivos: tuple


def decidir(score_xgboost: float | None, jev: JevResult | None, limiares: Limiares = Limiares()) -> Decisao:
    acao, motivos = Acao.APROVAR, []

    if score_xgboost is None:
        motivos.append("XGBOOST_INDISPONIVEL")
    elif score_xgboost >= limiares.xgboost_recusa:
        acao = Acao.RECUSAR
        motivos.append("XGBOOST_SCORE_ALTO")

    if jev is None:
        motivos.append("JEV_INDISPONIVEL")
        return Decisao(acao, tuple(motivos))

    acao_jev, motivos_jev = _avaliar_contexto(jev, limiares)
    return Decisao(max(acao, acao_jev), tuple(motivos + motivos_jev))


def _avaliar_contexto(jev: JevResult, limiares: Limiares) -> tuple[Acao, list]:
    golpe = jev.choices.get(GOLPE)
    alertas = []
    if golpe is not None and golpe.choice not in OPCOES_GOLPE:
        golpe = None  # rótulo fora das opções: a pergunta não vale
        alertas.append("JEV_ESCOLHA_DESCONHECIDA")
    faltando = [nome for nome in SINAIS if nome not in jev.nouls]
    if golpe is None and len(faltando) == len(SINAIS):
        return Acao.APROVAR, [*alertas, "JEV_RESPOSTA_INCOMPLETA"]  # nada aproveitável: fail-open
    if golpe is None or faltando:
        alertas.append("JEV_RESPOSTA_INCOMPLETA")

    sinais = [f"SINAL_{nome.upper()}" for nome in SINAIS if jev.nouls.get(nome, 0.0) >= limiares.sinal]

    if golpe is None:
        return (Acao.CONFIRMAR_COM_CLIENTE if sinais else Acao.APROVAR), [*alertas, *sinais]
    if golpe.confidence < limiares.confianca_minima:
        return Acao.CONFIRMAR_COM_CLIENTE, [*alertas, "JEV_INCERTO", *sinais]
    if golpe.choice != NENHUM:
        motivos = [*alertas, f"GOLPE_{golpe.choice.upper()}", *sinais]
        if golpe.confidence >= limiares.confianca_alta or sinais:
            return Acao.RETER_PARA_ANALISE, motivos
        return Acao.CONFIRMAR_COM_CLIENTE, motivos
    if sinais:
        return Acao.CONFIRMAR_COM_CLIENTE, [*alertas, *sinais]
    return Acao.APROVAR, alertas
