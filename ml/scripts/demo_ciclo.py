"""
Ciclo de vida do modelo de fraude, de ponta a ponta, em dados SINTÉTICOS.

    python scripts/demo_ciclo.py            n=100.000 por treino
    python scripts/demo_ciclo.py --rapido   o que o CI roda (n=50.000)

Roda tudo numa pasta temporária, com o serviço Flask de verdade (test client):
    1. v1 em produção, tráfego habitual: PSI estável.
    2. A população muda (cenário nova_fraude): o PSI acusa e a v1 perde fraudes.
    3. v2, treinada só com dados novos, em sombra: mostra onde decidiria diferente.
       O portão REPROVA: ela piora no padrão antigo.
    4. v3, treinada com dados antigos e novos: ainda perde no padrão antigo,
       ganha muito no novo. O critério v1 (tolerância zero) REPROVA de novo.
    5. Critério v2 HIPOTÉTICO, escolhido DEPOIS de ver a v3 (só nesta demo, numa
       pasta temporária): aceita até 3 pontos de perda no padrão antigo se ganhar
       20 no novo. O mecanismo não impede essa escolha; ele obriga a fazê-la às
       claras: o portão se recusa a avaliar a v3 com a régua nova, a v4 é treinada
       sob o critério v2, roda em sombra, passa no portão e é promovida. O serviço
       troca de modelo sem redeploy.
    6. "Incidente": reversão para a v1, também sem redeploy.

O critério real do repositório (criterio_promocao.json) continua o v1.
Mudar a régua é decisão de quem responde pelo antifraude.
Sai com código 1 se algum passo não acontecer como o esperado.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))


def titulo(texto: str) -> None:
    print(f"\n{'─' * 72}\n{texto}\n{'─' * 72}")


def conferir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise SystemExit(f"✗ esperado e não aconteceu: {mensagem}")
    print(f"  ✓ {mensagem}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--rapido", action="store_true", help="datasets menores (CI)")
    parser.add_argument("--resumo", type=Path, help="grava os números da demo em JSON")
    args = parser.parse_args()

    from registro import saida_utf8
    saida_utf8()

    n_treino = 50_000 if args.rapido else 100_000
    n_trafego = 1_000 if args.rapido else 2_000
    pasta = Path(tempfile.mkdtemp(prefix="bankmore-ml-"))
    os.environ.update({"ML_ARTIFACT_DIR": str(pasta), "REDIS_HOST": "", "ML_RECARGA_S": "0",
                       "ML_DRIFT_A_CADA": "100", "ML_THRESHOLD": "0"})

    import portao
    from dados import ALL_FEATURES, gerar
    from registro import Registro
    from retreinar import executar

    reg = Registro(pasta / "registro")
    resumo: dict = {"n_treino": n_treino, "n_trafego": n_trafego, "sintetico": True}

    def treinar(versao, cenario, seed, criterio=portao.CRITERIO_PATH):
        executar(versao, cenario=cenario, seed=seed, n=n_treino, fracao_fraude=0.02,
                 registro=reg, motivo="demo", verboso=False, criterio_path=criterio)
        print(f"  · {versao} treinada ({cenario}, seed {seed}) e registrada como candidata")

    # 1 ───────────────────────────────────────────────────────────────────
    titulo("1. v1 em produção, tráfego habitual")
    treinar("v1", "base", 42)
    reg.promover("v1", None, "primeira versão")
    import logging
    import app as servico_ml  # carrega a v1 do registro
    logging.getLogger("ml-service").setLevel(logging.WARNING)
    cliente = servico_ml.app.test_client()

    def trafego(cenario: str, seed: int) -> dict:
        df = gerar(n_trafego, 0.02, seed, cenario)
        barrou = {"modelo": {0: 0, 1: 0}, "consumidor": {0: 0, 1: 0}}
        for linha in df.to_dict(orient="records"):
            r = cliente.post("/predict", json={"features": {k: linha[k] for k in ALL_FEATURES}})
            assert r.status_code == 200, r.get_json()
            corpo, rotulo = r.get_json(), int(linha["is_fraude"])
            barrou["modelo"][rotulo] += corpo["decisao_recomendada"] == "REJEITAR"
            barrou["consumidor"][rotulo] += corpo["score"] >= portao.LIMIAR_CONSUMIDOR
        fraudes = int(df["is_fraude"].sum())
        return {"fraudes": fraudes, "legitimos": len(df) - fraudes,
                "fraudes_barradas": barrou["modelo"][1], "legitimos_barrados": barrou["modelo"][0],
                "fraudes_barradas_0_95": barrou["consumidor"][1], "legitimos_barrados_0_95": barrou["consumidor"][0],
                "drift": cliente.get("/drift").get_json()}

    def contar(t: dict) -> str:
        return (f"fraudes barradas {t['fraudes_barradas']}/{t['fraudes']} no limiar do modelo, "
                f"{t['fraudes_barradas_0_95']}/{t['fraudes']} no 0,95 dos consumidores")

    habitual = trafego("base", 101)
    psi_habitual = max(f["psi"] for f in habitual["drift"]["features"].values())
    print(f"  {contar(habitual)} · PSI máximo {psi_habitual:.3f}")
    conferir(habitual["drift"]["disponivel"] and psi_habitual < 0.10, "drift estável em todas as features (PSI < 0,10)")
    servico_ml.servico.janela.limpar()

    # 2 ───────────────────────────────────────────────────────────────────
    titulo("2. A população muda: valores maiores, mais Pix e um golpe novo (F6)")
    novo = trafego("nova_fraude", 202)
    psis = {k: v["psi"] for k, v in novo["drift"]["features"].items()}
    maior = max(psis, key=psis.get)
    print(f"  v1: {contar(novo)} (antes {habitual['fraudes_barradas']}/{habitual['fraudes']} e {habitual['fraudes_barradas_0_95']}/{habitual['fraudes']})")
    print("  PSI: " + ", ".join(f"{k} {v:.3f}" for k, v in sorted(psis.items(), key=lambda kv: -kv[1])[:4]))
    conferir(psis[maior] >= 0.25, f"o PSI acusa a mudança ({maior} = {psis[maior]:.3f}, nível alto)")
    resumo["drift"] = {"habitual_max": psi_habitual, "mudanca": psis,
                       "v1_habitual": habitual | {"drift": None}, "v1_mudanca": novo | {"drift": None}}

    # 3 ───────────────────────────────────────────────────────────────────
    titulo("3. v2 (só dados novos) em sombra, depois o portão")
    treinar("v2", "nova_fraude", 7)
    reg.colocar_em_sombra("v2", "demo")
    com_sombra = trafego("nova_fraude", 202)
    sombra = cliente.get("/sombra").get_json()
    conferir(com_sombra["fraudes_barradas"] == novo["fraudes_barradas"] and com_sombra["fraudes_barradas_0_95"] == novo["fraudes_barradas_0_95"],
             "a sombra não mudou nenhuma decisão")
    print(f"  sombra {sombra['sombra']}: {sombra['predicoes']} predições · decidiria diferente "
          f"no limiar do modelo {sum(sombra['modelo'].values())} vezes, no 0,95 dos consumidores {sum(sombra['consumidor'].values())} vezes")
    conferir(sum(sombra["consumidor"].values()) > 0, "a sombra registrou onde mudaria bloqueios")
    laudo_v2 = portao.avaliar(reg, "v2")
    portao.imprimir(laudo_v2)
    conferir(not laudo_v2["aprovado"], "o portão reprovou a v2 (piora no padrão antigo)")

    # 4 ───────────────────────────────────────────────────────────────────
    titulo("4. v3 (dados antigos + novos): ganho grande no novo, perda menor no antigo")
    treinar("v3", "base+nova_fraude", 11)
    laudo_v3 = portao.avaliar(reg, "v3")
    portao.imprimir(laudo_v3)
    conferir(not laudo_v3["aprovado"], "o critério v1 (tolerância zero) reprova a v3 também")
    print("  → A troca é explícita: ganhar o golpe novo custa um pouco do antigo. Decisão de negócio.")

    # 5 ───────────────────────────────────────────────────────────────────
    titulo("5. Critério v2 HIPOTÉTICO, escolhido depois de ver a v3: a régua muda às claras")
    criterio_v1 = json.loads(portao.CRITERIO_PATH.read_text(encoding="utf-8"))
    criterio_v2 = {**criterio_v1, "versao_do_criterio": 2, "escrito_em": "demo (depois de ver a v3)",
                   "tolerancia_por_cenario": {"base": 0.03}, "ganho_minimo_por_cenario": {"nova_fraude": 0.20},
                   "observacao": "HIPOTÉTICO, só na demo, escolhido depois de ver os resultados da v3: "
                                 "aceita até 3 pontos de perda no padrão antigo se ganhar 20 no novo."}
    caminho_v2 = pasta / "criterio_v2_hipotetico.json"
    caminho_v2.write_text(json.dumps(criterio_v2, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        portao.avaliar(reg, "v3", caminho_v2)
        conferir(False, "o portão recusaria avaliar a v3 com a régua nova")
    except portao.CriterioAlterado as erro:
        print(f"  {erro}")
        conferir(True, "o portão recusou avaliar a v3 com uma régua que não era a do treino dela")
    print("  O mecanismo não impede escolher a régua depois de ver resultados: obriga versão nova, retreino e laudo novo.")
    treinar("v4", "base+nova_fraude", 13, caminho_v2)
    reg.colocar_em_sombra("v4", "demo")
    trafego("nova_fraude", 303)
    sombra_v4 = cliente.get("/sombra").get_json()
    conferir(sombra_v4["sombra"] == "v4" and sombra_v4["predicoes"] > 0,
             f"a v4 rodou em sombra antes do portão ({sombra_v4['predicoes']} predições)")
    laudo_v4 = portao.avaliar(reg, "v4", caminho_v2)
    portao.imprimir(laudo_v4)
    conferir(laudo_v4["aprovado"], "a v4, treinada sob o critério v2, passa no portão")
    reg.promover("v4", laudo_v4, "laudo aprovado (critério v2 hipotético)")
    saude = cliente.get("/health").get_json()
    conferir(saude["model_version"] == "v4" and saude["shadow_version"] is None,
             "o serviço trocou para a v4 sem redeploy")
    depois = trafego("nova_fraude", 202)
    print(f"  tráfego novo, v1 → v4: {contar(novo)} → {contar(depois)}")
    print(f"  legítimos barrados no 0,95: v1 {novo['legitimos_barrados_0_95']}/{novo['legitimos']} → v4 {depois['legitimos_barrados_0_95']}/{depois['legitimos']}"
          " (amostra pequena; o laudo mede em 39.200 legítimos)")

    # 6 ───────────────────────────────────────────────────────────────────
    titulo("6. Incidente: reverter para a versão anterior")
    voltou = reg.reverter("demo: incidente simulado depois da promoção")
    saude = cliente.get("/health").get_json()
    conferir(voltou == "v1" and saude["model_version"] == "v1", "a produção voltou para a v1 sem redeploy")
    historico = reg.indice()["historico"]
    print("  histórico: " + " → ".join(f"{e['evento']}({e['versao']})" for e in historico[-6:]))

    def resumir(laudo):
        return [{"cenario": c["cenario"], "recall_producao": c["producao"]["recall"], "recall_candidato": c["candidato"]["recall"],
                 "diferenca": c["diferenca_recall"], "ic95": c["ic95_diferenca"], "aprovado": c["aprovado"],
                 "consumidor_0_95": c["consumidor"], "operacao": c["operacao"], "outros_fpr": c["outros_fpr"]}
                for c in laudo["conjuntos"]]

    resumo["portao"] = {"v2": resumir(laudo_v2), "v3": resumir(laudo_v3), "v4_criterio_v2_hipotetico": resumir(laudo_v4)}
    resumo["v4_trafego_novo"] = depois | {"drift": None}
    if args.resumo:
        args.resumo.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
    titulo(f"Ciclo completo. Registro em {pasta} (dados sintéticos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
