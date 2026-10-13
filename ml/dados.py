"""
Dataset SINTÉTICO de transações, com seed explícita e cenários de população.

Tudo aqui é gerado: não há dado real de cliente. Serve para exercitar o ciclo de
vida do modelo (registro, sombra, drift, portão de promoção), não para medir a
eficácia de um antifraude de verdade.

Cenários:
    base         população e padrões F1-F5 do treino original (Sprint 3).
    nova_fraude  a população mudou (valores ~80% maiores, mais Pix) e surgiu o
                 padrão F6, que o modelo base nunca viu: valor moderado, de dia,
                 4 a 8 vezes a média de 24h, com 2 a 4 Pix na última hora.
                 F4 só cobre 10x ou mais; F6 fica no meio da população normal.

Com o mesmo (n, fracao_fraude, seed, cenario), o dataset sai idêntico, e
hash_dados() devolve o mesmo valor: é o que torna o retreino reproduzível.
Os conjuntos de avaliação do portão usam um fluxo aleatório separado
(avaliacao=True), que nenhuma seed de treino reproduz.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

NUM_FEATURES = [
    "valor",
    "hora_do_dia",
    "dow",
    "count_tx_cpf_1h",
    "valor_medio_cpf_24h",
    "is_autotransferencia",
    "valor_p95_cpf_30d",
]
CAT_FEATURES = ["tipo"]
ALL_FEATURES = NUM_FEATURES + CAT_FEATURES


@dataclass(frozen=True)
class Cenario:
    nome: str
    valor_mu: float              # média do log do valor na população normal
    p_tipo: tuple                # PIX, TED, TEF na população normal
    fracao_f6: float             # parcela das fraudes que segue o padrão F6
    descricao: str


CENARIOS = {
    "base": Cenario("base", 5.0, (0.70, 0.20, 0.10), 0.0,
                    "população e fraudes F1-F5 do treino original"),
    "nova_fraude": Cenario("nova_fraude", 5.6, (0.85, 0.10, 0.05), 0.40,
                           "valores ~80% maiores, mais Pix e o padrão F6 (4-8x a média de 24h, de dia)"),
}


def gerar(n: int, fracao_fraude: float, seed: int, cenario: str = "base", avaliacao: bool = False) -> pd.DataFrame:
    """Transações sintéticas embaralhadas, com a coluna is_fraude.

    No cenário base, a sequência de sorteios é a mesma do train.py original:
    gerar(100000, 0.02, 42) reproduz o dataset da Sprint 3.

    "base+nova_fraude" mistura cenários em partes iguais (seed, seed+1, ...): é o
    retreino com dados antigos e novos juntos.

    avaliacao=True usa um fluxo aleatório separado (spawn_key próprio), que nenhuma
    seed de treino consegue reproduzir: o conjunto de avaliação do portão nunca
    aparece no treino, qualquer que seja a seed escolhida.
    """
    if "+" in cenario:
        partes = cenario.split("+")
        n_parte = n // len(partes)
        blocos = [gerar(n_parte if i < len(partes) - 1 else n - n_parte * (len(partes) - 1),
                        fracao_fraude, seed + i, nome, avaliacao)
                  for i, nome in enumerate(partes)]
        return _embaralhar(pd.concat(blocos, ignore_index=True), seed, avaliacao)
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario} (use {', '.join(CENARIOS)})")
    c = CENARIOS[cenario]
    rng = _rng_de_avaliacao(seed) if avaliacao else np.random.default_rng(seed)
    n_fraude_alvo = int(n * fracao_fraude)

    # ----- normal -----
    n_normal = n - n_fraude_alvo
    valor = rng.lognormal(mean=c.valor_mu, sigma=1.2, size=n_normal)
    tipo = rng.choice(["PIX", "TED", "TEF"], size=n_normal, p=list(c.p_tipo))
    hora = rng.choice(np.arange(24), size=n_normal, p=_hora_pdf())
    dow = rng.integers(0, 7, size=n_normal)
    count_1h = rng.poisson(lam=0.5, size=n_normal).clip(0, 10)
    valor_medio_24h = rng.lognormal(mean=c.valor_mu, sigma=0.8, size=n_normal)
    auto = (rng.random(n_normal) < 0.001).astype(int)
    p95_30d = valor_medio_24h * rng.uniform(1.5, 3.0, size=n_normal)

    normal = pd.DataFrame({
        "valor": valor,
        "tipo": tipo,
        "hora_do_dia": hora,
        "dow": dow,
        "count_tx_cpf_1h": count_1h,
        "valor_medio_cpf_24h": valor_medio_24h,
        "is_autotransferencia": auto,
        "valor_p95_cpf_30d": p95_30d,
        "is_fraude": 0,
    })

    # ----- fraude -----
    n_f6 = int(n_fraude_alvo * c.fracao_f6)
    n_classicas = n_fraude_alvo - n_f6
    n_por_padrao = n_classicas // 5
    fraudes = []

    # F1: valor muito alto
    fraudes.append(_amostra_fraude(rng, n_por_padrao, valor_min=15000, valor_max=80000))
    # F2: rajada (count_1h alto)
    f2 = _amostra_fraude(rng, n_por_padrao)
    f2["count_tx_cpf_1h"] = rng.integers(5, 12, size=n_por_padrao)
    fraudes.append(f2)
    # F3: noturno + valor alto
    f3 = _amostra_fraude(rng, n_por_padrao, valor_min=3000, valor_max=15000)
    f3["hora_do_dia"] = rng.integers(0, 6, size=n_por_padrao)
    fraudes.append(f3)
    # F4: valor 10x a 30x a média do CPF
    f4 = _amostra_fraude(rng, n_por_padrao)
    f4["valor"] = f4["valor_medio_cpf_24h"] * rng.uniform(10, 30, size=n_por_padrao)
    fraudes.append(f4)
    # F5: autotransferência (sempre fraude no dataset)
    f5 = _amostra_fraude(rng, n_classicas - 4 * n_por_padrao)
    f5["is_autotransferencia"] = 1
    fraudes.append(f5)
    # F6 (só em nova_fraude): valor moderado, de dia, 4-8x a média, 2-4 Pix na última hora
    if n_f6:
        medio = rng.lognormal(c.valor_mu, 0.8, size=n_f6)
        f6 = pd.DataFrame({
            "valor": medio * rng.uniform(4, 8, size=n_f6),
            "tipo": rng.choice(["PIX", "TED", "TEF"], size=n_f6, p=[0.9, 0.07, 0.03]),
            "hora_do_dia": rng.integers(9, 19, size=n_f6),
            "dow": rng.integers(0, 5, size=n_f6),
            "count_tx_cpf_1h": rng.integers(2, 5, size=n_f6),
            "valor_medio_cpf_24h": medio,
            "is_autotransferencia": 0,
            "valor_p95_cpf_30d": medio * rng.uniform(1.5, 3.0, size=n_f6),
            "is_fraude": 1,
        })
        fraudes.append(f6)

    df = pd.concat([normal, *fraudes], ignore_index=True)
    return _embaralhar(df, seed, avaliacao)


_SPAWN_AVALIACAO = (2023,)  # marca do fluxo de avaliação; default_rng(int) nunca tem spawn_key


def _rng_de_avaliacao(seed: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=_SPAWN_AVALIACAO)))


def _embaralhar(df: pd.DataFrame, seed: int, avaliacao: bool) -> pd.DataFrame:
    if avaliacao:
        return df.iloc[_rng_de_avaliacao(seed + 1).permutation(len(df))].reset_index(drop=True)
    return df.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def descrever(cenario: str) -> str:
    """Descrição legível de um cenário ou de uma mistura (base+nova_fraude)."""
    nomes = cenario.split("+")
    for nome in nomes:
        if nome not in CENARIOS:
            raise ValueError(f"cenário desconhecido: {nome} (use {', '.join(CENARIOS)})")
    if len(nomes) == 1:
        return CENARIOS[cenario].descricao
    return "mistura em partes iguais: " + "; ".join(f"{n} ({CENARIOS[n].descricao})" for n in nomes)


def hash_dados(df: pd.DataFrame) -> str:
    """sha256 do conteúdo (linhas, colunas e ordem), com números arredondados a 6 casas.

    O arredondamento torna o hash igual no Windows e no Linux: o exp() das
    bibliotecas de cada sistema pode diferir no último dígito. Qualquer mudança
    real de valor (acima de 1e-6) muda o hash.
    """
    linhas = pd.util.hash_pandas_object(df.round(6), index=True).values.tobytes()
    colunas = "|".join(map(str, df.columns)).encode("utf-8")
    return "sha256:" + hashlib.sha256(colunas + linhas).hexdigest()


def _hora_pdf() -> np.ndarray:
    """Distribuição da hora do dia (pico 9-22h)."""
    h = np.array([0.2, 0.15, 0.10, 0.10, 0.10, 0.10,   # 0-5h
                  0.30, 0.50, 0.80, 1.20, 1.40, 1.60,  # 6-11h
                  1.70, 1.80, 1.70, 1.50, 1.30, 1.20,  # 12-17h
                  1.10, 1.00, 0.90, 0.70, 0.50, 0.30]) # 18-23h
    return h / h.sum()


def _amostra_fraude(rng, n: int, valor_min: float = None, valor_max: float = None) -> pd.DataFrame:
    valor = (rng.uniform(valor_min, valor_max, size=n)
             if valor_min is not None else rng.lognormal(5.5, 1.0, size=n))
    return pd.DataFrame({
        "valor": valor,
        "tipo": rng.choice(["PIX", "TED", "TEF"], size=n, p=[0.5, 0.3, 0.2]),
        "hora_do_dia": rng.choice(np.arange(24), size=n, p=_hora_pdf()),
        "dow": rng.integers(0, 7, size=n),
        "count_tx_cpf_1h": rng.poisson(lam=0.5, size=n).clip(0, 10),
        "valor_medio_cpf_24h": rng.lognormal(5.0, 0.8, size=n),
        "is_autotransferencia": (rng.random(n) < 0.005).astype(int),
        "valor_p95_cpf_30d": rng.lognormal(5.5, 0.8, size=n) * 2.0,
        "is_fraude": 1,
    })
