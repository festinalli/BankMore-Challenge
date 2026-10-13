"""
Drift das features e do score por PSI (Population Stability Index).

A referência vem do treino e fica na ficha do modelo:
    - features contínuas: bordas das faixas (decis do treino) e proporção em cada faixa;
    - features discretas (até 30 valores distintos no treino, como hora, dia da
      semana, contagem e flags) e categóricas: proporção de cada valor, mais uma
      faixa "_outra" para o que o treino nunca viu. Decis não servem para elas:
      as bordas se repetem e mudanças como 0 → 1 ficariam invisíveis.
O serviço guarda uma janela das transações recentes e compara.

    PSI = Σ (observado - esperado) · ln(observado / esperado)

Leitura usual no mercado (regra de bolso, não lei):
    < 0,10  estável · 0,10 a 0,25  moderado · > 0,25  alto (investigar e retreinar)

Valores None na janela (feature que veio de placeholder, não do feature store)
ficam fora do cálculo daquela feature: senão o PSI mediria o placeholder, não a
população. Com menos de MINIMO_DE_AMOSTRAS valores, a feature não é calculada:
com janelas pequenas, o próprio ruído passa de 0,10.
"""
from __future__ import annotations

import math
from collections import deque
from threading import Lock

import numpy as np

from dados import CAT_FEATURES, NUM_FEATURES

EPS = 1e-4
MODERADO, ALTO = 0.10, 0.25
MINIMO_DE_AMOSTRAS = 1000
MAX_VALORES_DISCRETOS = 30


def psi(esperado: list[float], observado: list[float]) -> float:
    """PSI entre duas distribuições sobre as mesmas faixas (proporções somam 1)."""
    if len(esperado) != len(observado):
        raise ValueError("as distribuições precisam ter as mesmas faixas")
    total = 0.0
    for e, o in zip(esperado, observado):
        e, o = max(e, EPS), max(o, EPS)
        total += (o - e) * math.log(o / e)
    return float(total)


def classificar(valor: float) -> str:
    return "alto" if valor > ALTO else "moderado" if valor >= MODERADO else "estavel"


def _bordas(valores: np.ndarray, faixas: int = 10) -> list[float]:
    quantis = np.quantile(valores, np.linspace(0, 1, faixas + 1)[1:-1])
    return sorted({float(q) for q in quantis})


def _proporcoes_continuas(valores, bordas: list[float]) -> list[float]:
    valores = np.asarray(valores, dtype=float)
    contagem = np.bincount(np.searchsorted(bordas, valores, side="right"), minlength=len(bordas) + 1)
    return (contagem / max(len(valores), 1)).tolist()


def _chave(valor) -> str:
    """Valor discreto como texto estável: 3, 3.0 e "3" viram "3"."""
    if isinstance(valor, (int, float, np.integer, np.floating)) and float(valor).is_integer():
        return str(int(valor))
    return str(valor)


def _proporcoes_discretas(valores, categorias: list[str]) -> list[float]:
    contagem = {c: 0 for c in [*categorias, "_outra"]}
    for v in valores:
        chave = _chave(v)
        contagem[chave if chave in contagem else "_outra"] += 1
    total = max(len(valores), 1)
    return [contagem[c] / total for c in [*categorias, "_outra"]]


def referencia(X, scores) -> dict:
    """Referência de drift a partir dos dados de treino (DataFrame) e dos scores do holdout."""
    ref = {"continuas": {}, "discretas": {}, "score": {}}
    for nome in [*NUM_FEATURES, *CAT_FEATURES]:
        coluna = X[nome]
        distintos = coluna.unique()
        if nome in CAT_FEATURES or len(distintos) <= MAX_VALORES_DISCRETOS:
            categorias = sorted({_chave(v) for v in distintos})
            ref["discretas"][nome] = {"categorias": categorias, "esperado": _proporcoes_discretas(coluna, categorias)}
        else:
            bordas = _bordas(coluna.to_numpy(dtype=float))
            ref["continuas"][nome] = {"bordas": bordas, "esperado": _proporcoes_continuas(coluna, bordas)}
    bordas = _bordas(np.asarray(scores, dtype=float))
    ref["score"] = {"bordas": bordas, "esperado": _proporcoes_continuas(scores, bordas)}
    return ref


def calcular(ref: dict, linhas: list[dict], scores: list[float], minimo: int = 0) -> dict:
    """PSI de cada feature e do score. Ignora None; pula a feature com menos de `minimo` valores."""
    resultado = {"amostras": len(linhas), "features": {}, "score": None, "puladas": []}
    for grupo, proporcoes in (("continuas", _proporcoes_continuas), ("discretas", _proporcoes_discretas)):
        for nome, r in ref[grupo].items():
            valores = [l[nome] for l in linhas if l.get(nome) is not None]
            if len(valores) < max(minimo, 1):
                resultado["puladas"].append(nome)
                continue
            chave = "bordas" if grupo == "continuas" else "categorias"
            resultado["features"][nome] = psi(r["esperado"], proporcoes(valores, r[chave]))
    if len(scores) >= max(minimo, 1):
        resultado["score"] = psi(ref["score"]["esperado"], _proporcoes_continuas(scores, ref["score"]["bordas"]))
    return resultado


class Janela:
    """Últimas N transações vistas pelo serviço, para o PSI ao vivo."""

    def __init__(self, tamanho: int = 5000):
        self._linhas: deque = deque(maxlen=tamanho)
        self._scores: deque = deque(maxlen=tamanho)
        self._lock = Lock()

    def adicionar(self, features: dict, score: float, placeholders: frozenset = frozenset()) -> None:
        linha = {k: (None if k in placeholders else features[k]) for k in (*NUM_FEATURES, *CAT_FEATURES)}
        with self._lock:
            self._linhas.append(linha)
            self._scores.append(score)

    def limpar(self) -> None:
        with self._lock:
            self._linhas.clear()
            self._scores.clear()

    def __len__(self) -> int:
        return len(self._linhas)

    def calcular(self, ref: dict) -> dict | None:
        with self._lock:
            linhas, scores = list(self._linhas), list(self._scores)
        if len(linhas) < MINIMO_DE_AMOSTRAS:
            return None
        return calcular(ref, linhas, scores, MINIMO_DE_AMOSTRAS)
