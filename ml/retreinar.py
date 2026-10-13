"""
Retreino reproduzível: gera o dataset, treina e registra a versão como CANDIDATA.

    python retreinar.py --versao xgboost-v2 --cenario nova_fraude [--seed 7] [--n 100000]

Com os mesmos argumentos (e as mesmas bibliotecas), o dataset sai idêntico (mesmo
hash_dados) e as métricas também. A ficha guarda o que for preciso para refazer
o treino e auditar a decisão: hash dos dados, hash do código de treino, hash da
régua de promoção (critério, gerador da avaliação e código do portão), versões
das bibliotecas, plataforma e a referência de drift.

O candidato não decide nada. Próximos passos: sombra (registro.py), portão
(portao.py) e, se aprovado, promoção.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from importlib.metadata import version as versao_pacote
from pathlib import Path

import drift
from dados import CENARIOS, descrever, gerar, hash_dados
from registro import ErroDeRegistro, Registro, agora, saida_utf8

AQUI = Path(__file__).resolve().parent
CRITERIO_PATH = Path(os.getenv("ML_CRITERIO_PATH", AQUI / "criterio_promocao.json"))
CODIGO_DE_TREINO = ("dados.py", "train.py", "retreinar.py", "drift.py")


def hash_arquivos(nomes=CODIGO_DE_TREINO) -> str:
    h = hashlib.sha256()
    for nome in nomes:
        h.update(nome.encode())
        # Normaliza fim de linha: o mesmo código dá o mesmo hash no Windows e no Linux.
        h.update((AQUI / nome).read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + h.hexdigest()


REGUA = ("dados.py", "portao.py")  # gerador dos conjuntos de avaliação e código da métrica/regra


def hash_criterio(caminho: Path = CRITERIO_PATH) -> str:
    """Hash da régua: o critério, o gerador dos conjuntos de avaliação e o código do portão.

    Vai na ficha de cada candidato. Se a régua mudar depois do treino, o portão
    recusa avaliar: o laudo sempre usa a régua vigente quando o candidato foi
    treinado. Isso não impede escolher uma régua nova depois de ver resultados;
    impede que a troca passe sem versão nova, retreino e laudo novo.
    """
    conteudo = json.dumps(json.loads(caminho.read_text(encoding="utf-8")), sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(conteudo.encode("utf-8"))
    for nome in REGUA:
        h.update(b"|" + nome.encode() + b"|")
        h.update((AQUI / nome).read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + h.hexdigest()


def bibliotecas() -> dict:
    return {p: versao_pacote(p) for p in ("xgboost", "scikit-learn", "numpy", "pandas")}


def plataforma() -> dict:
    return {"python": platform.python_version(), "sistema": platform.platform()}


def executar(versao: str, *, cenario: str, seed: int, n: int, fracao_fraude: float,
             registro: Registro, motivo: str = "retreino", verboso: bool = True,
             criterio_path: Path = CRITERIO_PATH) -> dict:
    from train import treinar  # importa sklearn/xgboost só aqui

    if versao in registro.indice()["versoes"]:
        raise ErroDeRegistro(f"versão {versao} já existe; versões são imutáveis")
    df = gerar(n, fracao_fraude, seed, cenario)
    hash_df = hash_dados(df)
    if verboso:
        print(f"▶ {versao}: cenário {cenario}, seed {seed}, n={n}, dados {hash_df[:19]}…")
    resultado = treinar(df, seed=seed, versao=versao, verboso=verboso)
    metricas = resultado["metrics"]

    ficha = {
        "criado_em": agora(),
        "motivo": motivo,
        "dados": {
            "sintetico": True,
            "cenario": cenario,
            "descricao": descrever(cenario),
            "seed": seed,
            "n_amostras": n,
            "fracao_fraude": fracao_fraude,
            "hash": hash_df,
        },
        "hash_codigo": hash_arquivos(),
        "hash_criterio": hash_criterio(criterio_path),
        "bibliotecas": bibliotecas(),
        "plataforma": plataforma(),
        "limiar": metricas["threshold_recall_85"],
        "metricas": metricas,
        "referencia_drift": drift.referencia(resultado["X_train"], resultado["scores_holdout"]),
        "comando": f"python retreinar.py --versao {versao} --cenario {cenario} --seed {seed} --n {n} --fracao {fracao_fraude}",
    }
    registro.registrar(versao, resultado["model_pipeline"], ficha)
    return {**resultado, "ficha": ficha}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Treina e registra uma versão candidata do modelo de fraude.")
    parser.add_argument("--versao", required=True, help="ex.: xgboost-v2 (imutável)")
    parser.add_argument("--cenario", default="base", help=f"um de {sorted(CENARIOS)} ou mistura com +, ex.: base+nova_fraude")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=100_000)
    parser.add_argument("--fracao", type=float, default=0.02)
    args = parser.parse_args(argv)
    saida_utf8()

    registro = Registro()
    try:
        executar(args.versao, cenario=args.cenario, seed=args.seed, n=args.n,
                 fracao_fraude=args.fracao, registro=registro)
    except ErroDeRegistro as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    print(f"\n✓ {args.versao} registrada como candidata em {registro.dir}")
    print(f"  próximos passos: python registro.py sombra {args.versao}  →  python portao.py {args.versao}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
