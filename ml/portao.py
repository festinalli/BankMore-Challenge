"""
Portão de promoção: o candidato só vira produção se o critério deixar.

O critério (criterio_promocao.json, v1): recall com taxa fixa de falso positivo
(1% das transações legítimas: Pix, TED e TEF), em conjuntos de avaliação gerados
num fluxo aleatório que nenhum treino reproduz; o candidato não pode ser pior
que a produção em nenhum conjunto.

O que o mecanismo garante: a ficha de cada candidato guarda o hash da régua
(critério + gerador da avaliação + este arquivo). Se a régua mudar depois do
treino, o portão recusa avaliar; o laudo sempre usa a régua vigente quando o
candidato foi treinado, e toda troca de régua aparece como versão nova. O que
ele NÃO garante: que ninguém escolha a régua depois de ver resultados. Retreinar
a mesma receita leva segundos. Isso é governança (quem aprova o critério), não código.

O laudo também mostra, só para informação:
    - intervalo de confiança da diferença de recall (bootstrap pareado);
    - recall em outros pontos de falso positivo (0,1% e 0,3%);
    - os números no limiar de operação de cada modelo (o do /predict) e no limiar
      dos consumidores (ML_LIMIAR_CONSUMIDOR, padrão 0,95: o Pix e o PyFlink
      barram com score >= 0,95 e ignoram o limiar da ficha).

    python portao.py <versao>            avalia contra a produção, grava o laudo
    python portao.py <versao> --promover  e promove se aprovado

Saída 0 se aprovado, 1 se reprovado, 2 se não deu para avaliar (CI usa isso).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

from dados import ALL_FEATURES, gerar, hash_dados
from registro import ErroDeRegistro, Registro, agora, saida_utf8
from retreinar import CRITERIO_PATH, bibliotecas, hash_criterio, plataforma

LIMIAR_CONSUMIDOR = float(os.getenv("ML_LIMIAR_CONSUMIDOR", "0.95"))
FPRS_INFORMATIVOS = (0.001, 0.003, 0.01)
REAMOSTRAGENS = 1000


class CriterioAlterado(ErroDeRegistro):
    """A régua mudou depois que o candidato foi treinado."""


def _limiar(legitimos: np.ndarray, fpr_alvo: float) -> float:
    return float(np.quantile(legitimos, 1 - fpr_alvo, method="higher"))


def recall_com_fpr_fixa(scores, y, fpr_alvo: float) -> dict:
    """Limiar que dá no máximo fpr_alvo nos legítimos e o recall nas fraudes com esse limiar.

    score > limiar = alerta; empates no limiar ficam do lado "não alerta".
    """
    scores, y = np.asarray(scores, dtype=float), np.asarray(y)
    legitimos, fraudes = scores[y == 0], scores[y == 1]
    if len(legitimos) == 0 or len(fraudes) == 0:
        raise ValueError("o conjunto de avaliação precisa de legítimos e de fraudes")
    limiar = _limiar(legitimos, fpr_alvo)
    return {
        "limiar": limiar,
        "recall": float(np.mean(fraudes > limiar)),
        "fpr": float(np.mean(legitimos > limiar)),
        "fraudes": int(len(fraudes)),
        "legitimos": int(len(legitimos)),
    }


def no_limiar(scores, y, limiar: float) -> dict:
    """Recall e falso positivo com um limiar dado (score >= limiar = alerta, como no /predict)."""
    scores, y = np.asarray(scores, dtype=float), np.asarray(y)
    return {"limiar": float(limiar),
            "recall": float(np.mean(scores[y == 1] >= limiar)),
            "fpr": float(np.mean(scores[y == 0] >= limiar))}


def ic_da_diferenca(scores_p, scores_c, y, fpr_alvo: float, seed: int,
                    reamostragens: int = REAMOSTRAGENS, nivel: float = 0.95) -> list[float]:
    """IC por bootstrap pareado da diferença de recall (candidato − produção).

    Reamostra legítimos e fraudes (os mesmos índices para os dois modelos) e
    recalcula os limiares a cada vez: capta a incerteza do limiar e do recall.
    """
    scores_p, scores_c, y = np.asarray(scores_p), np.asarray(scores_c), np.asarray(y)
    leg, fra = np.flatnonzero(y == 0), np.flatnonzero(y == 1)
    rng = np.random.default_rng(seed)
    diferencas = np.empty(reamostragens)
    for i in range(reamostragens):
        il, if_ = rng.choice(leg, len(leg)), rng.choice(fra, len(fra))
        recall_p = np.mean(scores_p[if_] > _limiar(scores_p[il], fpr_alvo))
        recall_c = np.mean(scores_c[if_] > _limiar(scores_c[il], fpr_alvo))
        diferencas[i] = recall_c - recall_p
    cauda = (1 - nivel) / 2
    return [float(np.quantile(diferencas, cauda)), float(np.quantile(diferencas, 1 - cauda))]


def avaliar(registro: Registro, candidato: str, criterio_path=CRITERIO_PATH) -> dict:
    registro.estado_de(candidato)  # precisa estar no índice (e o nome é validado)
    criterio = json.loads(Path(criterio_path).read_text(encoding="utf-8"))
    hash_atual = hash_criterio(Path(criterio_path))
    ficha = registro.ficha(candidato)
    if ficha["hash_criterio"] != hash_atual:
        raise CriterioAlterado(
            f"a régua mudou depois do treino de {candidato} "
            f"({ficha['hash_criterio'][:19]}… → {hash_atual[:19]}…). Retreine para avaliar com a régua nova."
        )
    producao = registro.producao()
    if producao is None:
        raise ErroDeRegistro("não há produção para comparar; a primeira versão é promovida sem portão")
    if producao == candidato:
        raise ErroDeRegistro(f"{candidato} já está em produção")

    modelos = {"producao": registro.carregar(producao), "candidato": registro.carregar(candidato)}
    limiares = {"producao": float(registro.ficha(producao)["limiar"]), "candidato": float(ficha["limiar"])}
    av = criterio["avaliacao"]
    estatistica = criterio.get("regra_estatistica")
    conjuntos = []
    for indice, cenario in enumerate(av["cenarios"]):
        df = gerar(av["n"], av["fracao_fraude"], av["seed"], cenario, avaliacao=True)
        X, y = df[ALL_FEATURES], df["is_fraude"].to_numpy()
        scores = {papel: m.predict_proba(X)[:, 1] for papel, m in modelos.items()}
        medidas = {papel: recall_com_fpr_fixa(s, y, criterio["fpr_alvo"]) for papel, s in scores.items()}
        diferenca = medidas["candidato"]["recall"] - medidas["producao"]["recall"]
        ic = ic_da_diferenca(scores["producao"], scores["candidato"], y, criterio["fpr_alvo"],
                             seed=av["seed"] + indice, reamostragens=(estatistica or {}).get("reamostragens", REAMOSTRAGENS),
                             nivel=(estatistica or {}).get("nivel", 0.95))
        tolerancia = criterio.get("tolerancia_por_cenario", {}).get(cenario, criterio["tolerancia"])
        ganho_minimo = criterio.get("ganho_minimo_por_cenario", {}).get(cenario)
        base_da_regra = ic[0] if estatistica else diferenca  # com regra estatística, vale o limite inferior do IC
        aprovado = base_da_regra >= -tolerancia and (ganho_minimo is None or base_da_regra >= ganho_minimo)
        conjuntos.append({
            "cenario": cenario,
            "hash_dados": hash_dados(df),
            "producao": medidas["producao"],
            "candidato": medidas["candidato"],
            "diferenca_recall": diferenca,
            "ic95_diferenca": ic,
            "tolerancia": tolerancia,
            "ganho_minimo": ganho_minimo,
            "regra_sobre": "limite inferior do IC" if estatistica else "diferença pontual",
            "aprovado": bool(aprovado),
            "outros_fpr": {f"{fpr:.3%}": {papel: recall_com_fpr_fixa(s, y, fpr)["recall"] for papel, s in scores.items()}
                           for fpr in FPRS_INFORMATIVOS},
            "operacao": {papel: no_limiar(s, y, limiares[papel]) for papel, s in scores.items()},
            "consumidor": {papel: no_limiar(s, y, LIMIAR_CONSUMIDOR) for papel, s in scores.items()},
        })

    aprovado = all(c["aprovado"] for c in conjuntos)
    falhas = [c["cenario"] for c in conjuntos if not c["aprovado"]]
    return {
        "emitido_em": agora(),
        "candidato": candidato,
        "producao": producao,
        "criterio": {**criterio, "hash": hash_atual},
        "conjuntos": conjuntos,
        "aprovado": aprovado,
        "motivo": ("candidato atende o critério em todos os conjuntos" if aprovado
                   else f"candidato não atende o critério em: {', '.join(falhas)}"),
        "ambiente": {"bibliotecas": bibliotecas(), "plataforma": plataforma()},
    }


def imprimir(laudo: dict) -> None:
    c = laudo["criterio"]
    print(f"Portão: {laudo['candidato']} contra produção {laudo['producao']}")
    print(f"Critério v{c['versao_do_criterio']} ({c['escrito_em']}): {c['metrica']} = {c['fpr_alvo']:.0%}")
    for conj in laudo["conjuntos"]:
        p, k = conj["producao"], conj["candidato"]
        marca = "ok   " if conj["aprovado"] else "FALHA"
        regra = f"tolera {conj['tolerancia']:.3f}"
        if conj["ganho_minimo"] is not None:
            regra += f", exige ganho {conj['ganho_minimo']:+.3f}"
        lo, hi = conj["ic95_diferenca"]
        print(f"  [{marca}] {conj['cenario']:<12} recall {p['recall']:.3f} → {k['recall']:.3f} "
              f"({conj['diferenca_recall']:+.3f}, IC95 {lo:+.3f} a {hi:+.3f}; {regra} sobre {conj['regra_sobre']})")
        outros = ", ".join(f"{fpr}: {v['producao']:.3f} → {v['candidato']:.3f}" for fpr, v in conj["outros_fpr"].items())
        print(f"          recall com outros FPR · {outros}")
        for rotulo, chave in (("limiar de cada modelo (/predict)", "operacao"), ("limiar dos consumidores", "consumidor")):
            a, b = conj[chave]["producao"], conj[chave]["candidato"]
            print(f"          {rotulo}: recall {a['recall']:.3f} → {b['recall']:.3f}, "
                  f"falso positivo {a['fpr']:.4%} → {b['fpr']:.4%}")
    print(f"→ {'APROVADO' if laudo['aprovado'] else 'REPROVADO'}: {laudo['motivo']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portão de promoção do modelo de fraude.")
    parser.add_argument("versao")
    parser.add_argument("--promover", action="store_true", help="promove se o laudo for aprovado")
    parser.add_argument("--criterio", type=Path, default=CRITERIO_PATH, help="arquivo do critério (padrão: criterio_promocao.json)")
    args = parser.parse_args(argv)
    saida_utf8()

    registro = Registro()
    try:
        laudo = avaliar(registro, args.versao, args.criterio)
    except (ErroDeRegistro, FileNotFoundError) as erro:
        print(f"não foi possível avaliar: {erro}", file=sys.stderr)
        return 2
    caminho = registro.gravar_laudo(laudo)
    imprimir(laudo)
    print(f"laudo: {caminho}")
    if laudo["aprovado"] and args.promover:
        registro.promover(args.versao, laudo, "portão aprovado")
        print(f"✓ {args.versao} promovida a produção (anterior: {laudo['producao']})")
    return 0 if laudo["aprovado"] else 1


if __name__ == "__main__":
    sys.exit(main())
