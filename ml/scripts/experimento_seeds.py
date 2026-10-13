"""
Gera a tabela do ADR 0023: quanto cada receita de retreino ganha ou perde contra
a v1, em várias seeds, com o critério v1 (1% de falso positivo). Dados SINTÉTICOS.

    python scripts/experimento_seeds.py [--saida resultado.json]   (~5 min)

Linhas:
    controle        a receita da própria v1 (cenário base, 100 mil), só trocando a seed:
                    mostra o ruído entre seeds, o piso abaixo do qual nenhuma diferença
                    significa "pior"
    só dados novos  nova_fraude, 100 mil
    mistura         base+nova_fraude, 100 mil, 200 mil e 400 mil

Para cada candidato: diferença de recall no padrão antigo e no cenário novo,
o IC95 da diferença no antigo (bootstrap pareado) e se o critério v1 e o critério
v2 hipotético da demo (até −3 pontos no antigo, ganho ≥ 20 no novo) aprovariam.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))

RECEITAS = [
    ("controle (receita da v1, outra seed)", "base", 100_000, list(range(1, 9))),
    ("só dados novos", "nova_fraude", 100_000, [7, 8, 9]),
    ("mistura antigos + novos", "base+nova_fraude", 100_000, list(range(11, 19))),
    ("mistura antigos + novos", "base+nova_fraude", 200_000, [11, 13, 15]),
    ("mistura antigos + novos", "base+nova_fraude", 400_000, [11, 13]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--reamostragens", type=int, default=500)
    args = parser.parse_args()

    import portao
    from registro import Registro, saida_utf8
    from retreinar import executar
    saida_utf8()
    portao.REAMOSTRAGENS = args.reamostragens

    resultado = {"sintetico": True, "producao": "v1 (base, seed 42, 100 mil)", "linhas": []}
    with tempfile.TemporaryDirectory(prefix="bankmore-ml-seeds-") as d:
        reg = Registro(Path(d) / "registro")
        executar("v1", cenario="base", seed=42, n=100_000, fracao_fraude=0.02, registro=reg, verboso=False)
        reg.promover("v1", None, "produção do experimento")
        for rotulo, cenario, n, seeds in RECEITAS:
            t = time.perf_counter()
            candidatos = []
            for seed in seeds:
                versao = f"{cenario.replace('+', '-')}-{n // 1000}k-s{seed}"
                executar(versao, cenario=cenario, seed=seed, n=n, fracao_fraude=0.02, registro=reg, verboso=False)
                laudo = portao.avaliar(reg, versao)
                c = {conj["cenario"]: conj for conj in laudo["conjuntos"]}
                antigo, novo = c["base"]["diferenca_recall"], c["nova_fraude"]["diferenca_recall"]
                candidatos.append({
                    "seed": seed, "antigo": antigo, "novo": novo, "ic95_antigo": c["base"]["ic95_diferenca"],
                    "aprova_v1": laudo["aprovado"], "aprova_v2_hipotetico": antigo >= -0.03 and novo >= 0.20,
                })
            linha = {"receita": rotulo, "cenario": cenario, "n": n, "seeds": seeds, "candidatos": candidatos}
            resultado["linhas"].append(linha)
            antigos = [x["antigo"] for x in candidatos]
            novos = [x["novo"] for x in candidatos]
            print(f"{rotulo:<38} n={n:>7,} seeds {seeds[0]}..{seeds[-1]:<3} "
                  f"antigo {min(antigos):+.3f} a {max(antigos):+.3f} (média {statistics.mean(antigos):+.3f}) · "
                  f"novo {min(novos):+.3f} a {max(novos):+.3f} · aprovados v1 {sum(x['aprova_v1'] for x in candidatos)}/{len(seeds)}, "
                  f"v2 hipotético {sum(x['aprova_v2_hipotetico'] for x in candidatos)}/{len(seeds)} · {time.perf_counter() - t:.0f} s",
                  flush=True)
    if args.saida:
        args.saida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
