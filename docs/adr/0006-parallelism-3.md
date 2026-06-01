# ADR 0006 — PyFlink parallelism = 3

- **Data:** 2026-05-16
- **Status:** Aceita

## Contexto

Antes: `env.set_parallelism(1)` — single-slot. Toda chamada síncrona ao
`/predict` (~70ms) era sequencial → throughput limitado a ~5 req/s e
latência p95 ~4300ms ponta-a-ponta.

PyFlink 1.18 Python API **não tem `AsyncFunction` nativa** (só Java). Opções
pra desbloquear o slot do TaskManager durante chamadas HTTP:

## Alternativas

| Opção | Avaliação |
|---|---|
| **Mudar parallelism = 3** (escolhida) | Match exato com partitions do source (`transferencia.solicitada --partitions 3`). Cada slot lê 1 partition independente. |
| **Mudar parallelism = 8** (ou mais) | Slots além das partitions ficam idle (Kafka assigna no máximo 1 partition por consumer). Desperdício. |
| **`ThreadPoolExecutor` dentro do operator** | Cada `process_element` enfileira HTTP call em thread pool. Complicado por reentrância no `MapState` (state é keyed e não thread-safe). |
| **AsyncIO em Java + wrapper Python** | Foge do escopo "Python-only" do case. |
| **Reescrever em Java** | Perde "PyFlink" da narrativa de entrevista. |

## Decisão

`env.set_parallelism(int(os.getenv("PARALLELISM", "3")))` —
parametrizável por env, default 3.

## Verificação

[`scripts/bench.sh`](../../scripts/bench.sh) — micro-benchmark com N=20
transferências paralelas de CPFs distintos (1 por conta — evita burst rule):

| Métrica | parallelism=1 | parallelism=3 | Δ |
|---|---|---|---|
| Latência avg | 4177 ms | 2487 ms | **−40%** |
| p50 | 4165 ms | 2564 ms | **−38%** |
| p95 | 4338 ms | 2826 ms | **−35%** |
| Throughput end-to-end | 4.5 req/s | 6.4 req/s | **+42%** |

## Consequências

- ✅ Latência −40%, throughput +42% sem refator de código.
- ✅ Sem novos bugs — checkpoint EXACTLY_ONCE preservado (keyBy continua particionando state corretamente).
- ⚠️ Saturação só vai pra ~3× a linha de base. Pra scaling além disso, partições do Kafka precisam subir (`--alter --partitions 6`) + parallelism acompanha.
- ⚠️ `ThreadPoolExecutor` ainda é caminho futuro se ML p99 subir significativamente. Documentado como Sprint 5.
