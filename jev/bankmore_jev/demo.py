"""Demonstração: Pix sintéticos passam pelo XGBoost e pelo Jev; o código decide.

Sem dados reais: os cenários são fictícios e não há CPF nem nome no estado.
O score do XGBoost vem do cenário (exemplo) ou do fraud-ml real, com --ml-url.
"""
from __future__ import annotations

import http.client
import json
import logging
import math
import os
import statistics
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

from .client import DEFAULT_MODEL, PRAZO_MAXIMO_S, ChoiceAnswer, JevClient, JevError, JevResult, urllib_transport
from .policy import Acao, decidir
from .questions import GOLPE, OPCOES_GOLPE, SINAIS, perguntas
from .state import Pix, montar_estado

CENARIOS = Path(__file__).with_name("scenarios.json")

log = logging.getLogger("bankmore_jev")
_SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_ROTULOS = {
    Acao.APROVAR: "APROVAR",
    Acao.CONFIRMAR_COM_CLIENTE: "CONFIRMAR COM CLIENTE",
    Acao.RETER_PARA_ANALISE: "RETER PARA ANÁLISE",
    Acao.RECUSAR: "RECUSAR",
}
_CORES = {
    Acao.APROVAR: "\033[32m",
    Acao.CONFIRMAR_COM_CLIENTE: "\033[33m",
    Acao.RETER_PARA_ANALISE: "\033[35m",
    Acao.RECUSAR: "\033[31m",
}
_RESET = "\033[0m"


def carregar_cenarios(caminho: Path = CENARIOS) -> list[dict]:
    return json.loads(caminho.read_text(encoding="utf-8"))


def pix_do_cenario(cenario: dict) -> Pix:
    dados = cenario["pix"]
    medio_24h = dados.get("valor_medio_24h")
    return Pix(
        valor=Decimal(dados["valor"]),
        hora_local=dados["hora_local"],
        tipo_iniciacao=dados["tipo_iniciacao"],
        count_tx_1h=dados["count_tx_1h"],
        valor_habitual=Decimal(dados["valor_habitual"]),
        primeiro_pix_para_destino=dados["primeiro_pix_para_destino"],
        chave_destino_idade_dias=dados["chave_destino_idade_dias"],
        dispositivo_novo=dados["dispositivo_novo"],
        motivo_informado=dados.get("motivo_informado", ""),
        historico=dados.get("historico", ""),
        valor_medio_24h=None if medio_24h is None else Decimal(medio_24h),
    )


def resposta_offline(cenario: dict) -> JevResult:
    """Resposta SIMULADA, escrita à mão no cenário: só para testes e para quem não tem chave."""
    gravada = cenario["jev_offline"]
    return JevResult(
        choices={GOLPE: ChoiceAnswer(gravada["golpe"]["choice"], gravada["golpe"]["confidence"], {})},
        nouls=dict(gravada["nouls"]),
        model="simulado",
        latency_ms=0.0,
    )


def score_do_fraud_ml(ml_url: str, pix: Pix, timeout_s: float = 2.0) -> float | None:
    """Chama o /predict real do fraud-ml, o mesmo do FraudeClient do Pix. Fail-open.

    Diferenças para o Pix real: sem cpfOrigem, o fraud-ml não consulta o Redis.
    O valor_p95_cpf_30d vai do cenário; o valor_medio_cpf_24h também, quando o
    cenário o define (nos outros, o fraud-ml usa o próprio valor). O dia da
    semana é fixo. O serviço é local, então a chamada ignora proxy.
    """
    features = {
        "valor": float(pix.valor),
        "tipo": "PIX",
        "hora_do_dia": pix.hora_local,
        "dow": 1,
        "count_tx_cpf_1h": pix.count_tx_1h,
        "is_autotransferencia": 0,
        "valor_p95_cpf_30d": float(pix.valor_habitual),
    }
    if pix.valor_medio_24h is not None:
        features["valor_medio_cpf_24h"] = float(pix.valor_medio_24h)
    try:
        request = urllib.request.Request(
            ml_url.rstrip("/") + "/predict",
            data=json.dumps({"features": features}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _SEM_PROXY.open(request, timeout=timeout_s) as response:
            bruto = json.loads(response.read())["score"]
        if isinstance(bruto, bool) or not isinstance(bruto, (int, float)):
            raise TypeError("score não numérico")
        score = float(bruto)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError, http.client.HTTPException) as falha:
        log.warning("fraud-ml indisponível (%s): seguindo sem score", type(falha).__name__)
        return None
    if not (math.isfinite(score) and 0.0 <= score <= 1.0):
        log.warning("fraud-ml devolveu score fora de [0, 1]: seguindo sem score")
        return None
    return score


def _imprimivel(texto):
    """Texto vindo da API vai para o terminal sem sequências de escape."""
    if texto is None:
        return None
    return "".join(c if c.isprintable() else "?" for c in str(texto))


def _timeout_do_ambiente(env) -> float | None:
    bruto = env.get("JEV_TIMEOUT_S", "2.0")
    try:
        valor = float(bruto.strip().replace(",", "."))
    except ValueError:
        return None
    return valor if 0 < valor <= PRAZO_MAXIMO_S else None


def executar(args, out=sys.stdout, err=sys.stderr, env=os.environ, transport=urllib_transport) -> int:
    cenarios = carregar_cenarios()
    if args.cenario is not None:
        cenarios = [c for c in cenarios if c["id"] == args.cenario]
        if not cenarios:
            print(f"Cenário {args.cenario} não existe.", file=err)
            return 2

    cliente = None
    if not args.offline:
        chave = env.get("TYPESAFE_API_KEY", "")
        if not chave.strip():
            print("Defina TYPESAFE_API_KEY (ou rode com --offline para respostas simuladas).", file=err)
            return 2
        timeout_s = _timeout_do_ambiente(env)
        if timeout_s is None:
            print(f"JEV_TIMEOUT_S deve ser um número de segundos entre 0 e {PRAZO_MAXIMO_S:g} (ex.: 2.0).", file=err)
            return 2
        try:
            cliente = JevClient(chave, model=env.get("TYPESAFE_MODEL") or DEFAULT_MODEL, timeout_s=timeout_s, transport=transport)
        except ValueError as falha:
            print(str(falha), file=err)  # a mensagem nunca inclui a chave
            return 2

    questions = perguntas(nenhum_primeiro=getattr(args, "nenhum_primeiro", False))
    resultados = [_avaliar(c, cliente, args.ml_url, questions) for c in cenarios]
    if args.json:
        for resultado in resultados:
            print(json.dumps(resultado), file=out)  # ASCII: válido em qualquer code page
    else:
        _imprimir(resultados, args, out)
    return 0


def _avaliar(cenario: dict, cliente: JevClient | None, ml_url: str | None, questions: dict) -> dict:
    pix = pix_do_cenario(cenario)
    score = score_do_fraud_ml(ml_url, pix) if ml_url else cenario["score_xgboost_exemplo"]

    erro = None
    if cliente is None:
        jev = resposta_offline(cenario)
    else:
        try:
            jev = cliente.ask(montar_estado(pix), questions)
        except JevError as falha:
            jev, erro = None, _imprimivel(falha)
        except Exception as falha:  # última rede do fail-open, como o catch do FraudeClient.cs
            jev, erro = None, f"falha inesperada ({type(falha).__name__})"
        if erro:
            log.warning("Jev indisponível no cenário %s: %s", cenario["id"], erro)

    so_xgboost = decidir(score, None).acao
    decisao = decidir(score, jev)
    golpe = jev.choices.get(GOLPE) if jev else None
    rotulo = None
    if golpe is not None:
        rotulo = golpe.choice if golpe.choice in OPCOES_GOLPE else "(rótulo desconhecido)"
    return {
        "id": cenario["id"],
        "titulo": cenario["titulo"],
        "categoria": cenario["categoria"],
        "score_xgboost": score,
        "so_xgboost": so_xgboost.name,
        "jev": None if jev is None else {
            "modelo": _imprimivel(jev.model),
            "golpe": rotulo,
            "confianca": golpe.confidence if golpe else None,
            "sinais": {nome: jev.nouls.get(nome) for nome in SINAIS},
            "latencia_ms": round(jev.latency_ms, 1),
        },
        "erro_jev": erro,
        "decisao": decisao.acao.name,
        "motivos": list(decisao.motivos),
    }


def _imprimir(resultados: list[dict], args, out) -> None:
    cor = not args.sem_cor and not os.environ.get("NO_COLOR") and getattr(out, "isatty", lambda: False)()
    modo = "respostas SIMULADAS (--offline)" if args.offline else "Jev ao vivo"
    fonte = f"fraud-ml em {args.ml_url}" if args.ml_url else "score de exemplo do cenário"
    ordem = "'nenhum' primeiro" if getattr(args, "nenhum_primeiro", False) else "golpes primeiro"

    print("BankMore · antifraude Pix com Jev", file=out)
    print("O XGBoost lê os números, o Jev lê o contexto, o código decide.", file=out)
    print(f"Jev: {modo}  |  XGBoost: {fonte}  |  opções da Choice: {ordem}\n", file=out)
    print(f"{'#':<3}{'Cenário':<32}{'XGBoost':>8}  {'Só XGBoost':<12}{'Jev: golpe (confiança)':<28}{'Com Jev':<24}{'Jev ms':>7}", file=out)

    for r in resultados:
        jev = r["jev"]
        if jev is None:
            leitura, latencia = "indisponível", "-"
        else:
            leitura = f"{jev['golpe']} ({jev['confianca']:.0%})" if jev["golpe"] else "resposta incompleta"
            latencia = "-" if args.offline else f"{jev['latencia_ms']:.0f}"
        score = "-" if r["score_xgboost"] is None else f"{r['score_xgboost']:.2f}".replace(".", ",")
        decisao = Acao[r["decisao"]]
        rotulo = f"{_ROTULOS[decisao]:<24}"
        if cor:
            rotulo = f"{_CORES[decisao]}{rotulo}{_RESET}"
        so_xgb = _ROTULOS[Acao[r["so_xgboost"]]]
        print(f"{r['id']:<3}{r['titulo']:<32}{score:>8}  {so_xgb:<12}{leitura:<28}{rotulo}{latencia:>7}", file=out)

    print("\nMotivos:", file=out)
    for r in resultados:
        motivos = ", ".join(r["motivos"]) or "nenhum"
        extra = f"  (erro: {r['erro_jev']})" if r["erro_jev"] else ""
        print(f"  {r['id']}. {motivos}{extra}", file=out)

    print("", file=out)
    for linha in resumo(resultados):
        print(linha, file=out)
    if args.offline:
        print("Atenção: respostas do Jev SIMULADAS. Rode sem --offline, com TYPESAFE_API_KEY, para a demonstração real.", file=out)


def resumo(resultados: list[dict]) -> list[str]:
    """Os números da demonstração, contados a partir da categoria de cada cenário."""
    linhas = []
    mudou = sum(1 for r in resultados if r["decisao"] != r["so_xgboost"])
    linhas.append(f"O Jev mudou a decisão em {mudou} de {len(resultados)} Pix (só para mais cautela).")

    golpes = [r for r in resultados if r["categoria"] == "golpe"]
    if golpes:
        passariam = [r for r in golpes if r["so_xgboost"] == Acao.APROVAR.name]
        segurados = sum(1 for r in passariam if r["decisao"] != Acao.APROVAR.name)
        linhas.append(
            f"Golpes de engenharia social: o XGBoost sozinho aprovaria {len(passariam)} de {len(golpes)}; "
            f"desses, o Jev segurou {segurados} (retidos ou com confirmação)."
        )
    legitimos = [r for r in resultados if r["categoria"] == "legitimo"]
    if legitimos:
        atrito = [str(r["id"]) for r in legitimos if r["decisao"] != r["so_xgboost"]]
        detalhe = f" (cenário {', '.join(atrito)})" if atrito else ""
        linhas.append(f"Pix legítimos com atrito a mais por causa do Jev: {len(atrito)} de {len(legitimos)}{detalhe}.")

    respostas = [r["jev"] for r in resultados if r["jev"] and r["jev"]["modelo"] != "simulado"]
    if respostas:
        latencias = [j["latencia_ms"] for j in respostas]
        modelos = ", ".join(sorted({j["modelo"] for j in respostas}))
        linhas.append(
            f"Latência do Jev ({len(latencias)} chamadas, {modelos}): "
            f"mediana {statistics.median(latencias):.0f} ms, máxima {max(latencias):.0f} ms."
        )
    falhas = sum(1 for r in resultados if r["erro_jev"])
    if falhas:
        linhas.append(f"O Jev falhou em {falhas} chamada(s); nelas valeu a decisão do XGBoost (fail-open).")
    return linhas
