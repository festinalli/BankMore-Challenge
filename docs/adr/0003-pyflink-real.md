# ADR 0003 — PyFlink real (não detector Python puro)

- **Data:** 2026-05-13
- **Status:** Aceita

## Contexto

Sprint 1 entregou um `auto_approver.py` em Python puro — consumer Kafka simples
que aprovava tudo. Não tinha:
- State por CPF (regra de burst exigia memória)
- Event-time + watermark (replay determinístico)
- Checkpoint (recuperação de falhas)
- Exactly-once

## Alternativas avaliadas

| Opção | Avaliação |
|---|---|
| **Python puro + Redis pra state** | Funciona mas reinventa Flink. State partition manual, sem checkpoint automático, sem watermark. |
| **Flink em Java** | Caminho mais natural. Mas perde "PyFlink" do storyline de entrevista (case top destacava Python em streaming). |
| **PyFlink 1.18 real** (escolhida) | JVM + Python API. KeyedProcessFunction com `MapState`, RocksDB backend, EXACTLY_ONCE checkpoint. |

## Decisão

PyFlink 1.18 em **local-mode dentro do próprio container** (`fraud-detector`).
Não submete ao Flink JM/TM cluster externo — Sprint 5 separa pra escalar
horizontalmente.

## Configurações chave

[`fraud_detector_job.py`](../../pyflink/fraud_detector_job.py):

- `KeyedProcessFunction(FraudDecider)` com `MapState<long, byte>` pra burst window
- `StateTtlConfig` com TTL = 2× janela de burst (cleanup automático)
- `WatermarkStrategy.for_bounded_out_of_orderness(5s)` — tolera 5s de out-of-order
- `state.backend = rocksdb` + checkpoint a cada 60s, EXACTLY_ONCE mode
- Side outputs **simulados via `.filter()` downstream** — PyFlink 1.18 tem bug
  no `Context.output()` com `KeyedProcessFunction`; workaround é yield decision
  payload single-stream + filter por campo `decisao`.

## Problemas técnicos resolvidos (anotados)

3 stops em série pra subir:

| Sintoma | Causa real | Solução |
|---|---|---|
| `pip install apache-flink` timeout no daemon Docker | dep `apache-flink-libraries` é 220MB sdist | Download no host (`make pyflink-deps`) + `COPY` no Dockerfile |
| `pemja` "Include folder should be at /opt/java/openjdk/include but doesn't exist" | imagem `flink:1.18` tem só JRE, `pemja` compila contra JDK | `apt-get install openjdk-11-jdk-headless` + linkar `jni.h` |
| `'InternalKeyedProcessFunctionContext' has no attribute 'output'` | bug PyFlink 1.18 side outputs com Keyed | yield no operator + `.filter()` downstream |

## Consequências

- ✅ State persistido em RocksDB → recovery após restart sem perder janela burst.
- ✅ Event-time + watermark → replay de tópico produz mesmo resultado.
- ✅ EXACTLY_ONCE end-to-end (sink Kafka transacional + sink idempotente no Worker).
- ⚠️ Local-mode: sem isolamento JM/TM, restart do container reinicia o job
  do último checkpoint. Sprint 5: submeter ao cluster `flink-jm` separado.
- ⚠️ Side output via filter custa 1 dataflow extra (filter é stateless mas
  consome slot). Aceitável dado o bug do PyFlink.
