# BankMore — Real-Time Fraud Detection + PIX

**Novo módulo:** [Fraud Intelligence — investigação com MCP, RAG e revisão humana](investigation/README.md).
MVP isolado do pagamento, com demonstração sintética e integração opcional ao Kafka de transferências.

[Demonstração e diagramas C4](docs/showcase/README.md) · [Validação do MVP](investigation/VALIDATION.md) · [Servidor MCP](investigation/bankmore_intelligence/mcp_server.py)

![.NET 8](https://img.shields.io/badge/.NET%208-512BD4?logo=dotnet&logoColor=white)
![Angular](https://img.shields.io/badge/Angular-DD0031?logo=angular&logoColor=white)
![PyFlink 1.18](https://img.shields.io/badge/PyFlink%201.18-E6526F?logo=apacheflink&logoColor=white)
![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-231F20?logo=apachekafka&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

Sistema bancário event-driven com **detecção de fraude em tempo real** e um
**arranjo PIX completo** (DICT, liquidação ISO 20022, MED, QR EMVCo, PIX Automático,
NFC, Open Finance), com **mTLS na RSFN**.

Toda transferência passa por um job **PyFlink 1.18** (regras duras + **XGBoost**)
antes de ser efetivada. Todo PIX passa por **antifraude em dois níveis**: scoring
**inline síncrono** antes da liquidação (bloqueia) + **análise pós-liquidação em
streaming** que enriquece o feature store (observa). Arquitetura limpa (Clean
Architecture + CQRS + DDD) em 3 bounded contexts: ContaCorrente, Transferência e PIX.

> **Sprints 1–10 done.** Changelog resumido abaixo; decisões em `docs/adr/` (0001–0019).
> Validação: `make e2e` (7 cenários de transferência) + `make e2e-pix` (**10 fluxos PIX**).

<details>
<summary><b>📋 Changelog detalhado — Sprints 1–10</b> (clique para expandir)</summary>

> **Sprint 1 done** (11/05): stack 100% Docker, fluxo Solicitada → Worker.
>
> **Sprint 2 done** (16/05): detector com state, persistência de status no Postgres,
> 4 cenários e2e (feliz / auto-transf / valor alto / burst).
>
> **Sprint 2.5 done** (16/05): **PyFlink real** — JVM + `KeyedProcessFunction` +
> `MapState` com TTL + watermark + checkpoint EXACTLY_ONCE em RocksDB a cada 60s.
>
> **Sprint 3 done** (16/05): **ML em produção**. XGBoost (ROC-AUC 0.9993) treinado
> no build da imagem (`ml/train.py` com seed=42), servido por Flask + Gunicorn.
> PyFlink chama `/predict` síncrono com **fail-open** (timeout 2s → segue só com
> regras se ML cair). Decisão híbrida: regras DURAS primeiro (autotransf/burst/
> valor inválido) + score ML segundo (threshold 0.95). `modelo_versao` salvo na
> tabela `transferencia` (`rules-v1+xgboost-v1`).
>
> **Sprint 4.A+B done** (16/05): **Validação de saldo + Feature Store Redis**.
> Worker valida saldo dentro da transação (rejeitada → COMPENSADA com motivo
> `SALDO_INSUFICIENTE`). Worker popula feature store Redis (count_1h, valores_24h,
> valores_30d) por CPF origem após cada efetivação. ML service consulta Redis no
> `/predict` — features REAIS, não mais placeholders. 6º cenário no e2e valida saldo.
>
> **Sprint 4.C done** (16/05): **PyFlink parallelism = 3**. Antes single-slot
> sequencializava chamadas síncronas ao ML. Subindo pra 3 (match com partitions
> do `transferencia.solicitada`) dá distribuição real entre slots. Bench com 20
> tx paralelas — `scripts/bench.sh`:
> | métrica | parallelism=1 | parallelism=3 | delta |
> |---|---|---|---|
> | latência avg | 4177 ms | 2487 ms | **−40%** |
> | p95 | 4338 ms | 2826 ms | **−35%** |
> | throughput e2e | 4.5 req/s | 6.4 req/s | **+42%** |
>
> AsyncFunction nativo do PyFlink 1.18 só existe no Java API; ThreadPoolExecutor
> dentro do operator daria gain marginal sobre essa baseline (custo do ML já está
> em N slots). Cabe Sprint 5 se for medido como gargalo.
>
> **Sprint 4.D done** (16/05): **Painel ops em tempo real**. `FraudeOpsController`
> no `ContaCorrente.Api` expõe `GET /api/admin/fraude/stream` (SSE) que consome
> em paralelo `fraude.alerta` + `transferencia.rejeitada` com 2 consumers Kafka
> efêmeros (group ID novo por conexão, `AutoOffsetReset.Latest`). Envelope JSON
> enriquece com `evento` + `topico` + `recebidoEm` preservando todos os campos
> do detector (motivos, score, modelo_versao, latência). Frontend Angular em
> `/ops/fraude` (sem auth na v1) lista até 50 cards, cores por severidade, badge
> live/offline, contadores. Cenário 7 do e2e abre stream + dispara fraude +
> valida `data:` frame chegou.
>
> **Sprint 5.A done** (19/05): **Flink PrometheusReporter nativo**. JAR copiado
> de `plugins/` pra `lib/` (PyFlink local-mode não carrega plugins automaticamente)
> + reporter configurado via `Configuration()`. Porta `9249` exposta. Prometheus
> agora raspa **5 targets** (4 .NET/Python + Flink). Métricas auto-instrumentadas:
> `flink_jobmanager_numRunningJobs`, `flink_taskmanager_job_task_operator_KafkaProducer_record_send_rate`,
> `flink_jobmanager_job_lastCheckpointDuration`, etc.
>
> **Sprint 5.B done** (19/05): **Outbox pattern**. Tabela `transferencia_outbox`
> garante atomicidade Postgres↔Kafka. Handler grava transferência + outbox row
> na MESMA transação. `OutboxRelayHostedService` (BackgroundService) polling com
> `FOR UPDATE SKIP LOCKED`, `acks=all`, `enable.idempotence=true`, backoff
> exponencial. KafkaFlow producer removido da Transferencia.Api — só
> `Confluent.Kafka` no relay. Métricas Prometheus: `bankmore_outbox_*`.
>
> **Sprint 5.C done** (19/05): **Schemas Avro registrados no Schema Registry**.
> `contracts/avro/{solicitada,decidida}.avsc` viraram fonte de verdade.
> `make register-schemas` sobe 4 subjects com `compatibility=BACKWARD`.
> Kafka UI mostra schemas vinculados. **Híbrido**: payload Kafka continua JSON
> (migração pra Avro binário é Sprint 6 — ver ADR 0013).
>
> **Sprint 6.A done** (19/05): **DLQ no outbox**. Coluna `dead_letter_em` na
> `transferencia_outbox`; após `Outbox__MaxTentativas` (default 5), relay move
> automático. Endpoints admin `GET /api/admin/outbox/dlq` + `POST .../{id}/reprocess`.
> Métrica `bankmore_outbox_dlq_total{motivo}`. ADR 0014.
>
> **Sprint 6.B done** (19/05): **Avro binário no producer .NET** (consumer PyFlink
> ativação fica pra Sprint 7 — exige trocar `SimpleStringSchema` por bytes).
> `AvroSerdes.cs` lê schema do registry, monta `GenericRecord` field-by-field,
> usa `AvroSerializer<GenericRecord>` (wire format Confluent: magic byte +
> schema_id + body). Switch por env: `Outbox__AvroTopics=transferencia.solicitada`.
> Default OFF pra não quebrar consumer atual. `fastavro` + `requests` já no
> `Dockerfile.flink` esperando ativação. ADR 0015.
>
> **Sprint 4.E done** (19/05): **Prometheus + Grafana**. Instrumentação completa:
> - APIs .NET (`prometheus-net.AspNetCore`): `UseHttpMetrics()` + `/metrics`
> - Worker (`prometheus-net` + `MetricServer` na porta 9102): contadores de
>   transferência efetivada/compensada por tipo, tarifa cobrada (BRL),
>   histograma de duração da efetivação
> - ML service (`prometheus_client` no Flask): contadores por decisão,
>   histograma de latência do `predict_proba`, distribuição do score,
>   misses no Redis, gauge do threshold ativo
> - Prometheus 2.54 scraping 4 jobs a cada 15s (TSDB 24h)
> - Grafana 11.2 com dashboard provisionado `BankMore — Overview` (datasource
>   Prometheus configurado via provisioning YAML, anonymous viewer ligado)
>
> Limitação assumida: PyFlink job **não exporta** Prometheus — `prometheus_client`
> tem locks internos não-serializáveis pelo `cloudpickle` que o Flink usa pra
> distribuir o operator. Sprint 5 substitui por `flink-conf.yaml` com reporter
> nativo do Flink (JM/TM expõem métricas em porta dedicada).
>
> **Sprint 7 done:** **Avro binário end-to-end**. Consumer PyFlink decoda o wire
> format Confluent via `fastavro` (truque do `SimpleStringSchema('ISO-8859-1')` que
> preserva bytes 1-to-1, evitando JNI). Auth shared-secret nos endpoints admin do
> outbox (fail-closed). Retenção automática de DLQ (>30d). ADR 0016.
>
> **Sprint 8 done:** **PIX real**. Bounded context `BankMore.Pix` (Clean Arch/CQRS)
> + serviço `bacen-sim` (DICT + SPI/ISO 20022). Fluxos: pagamento por chave, BR Code
> EMVCo + CRC16, MED com `pacs.004` + estorno, PIX Automático (scheduler de
> recorrência), NFC single-use, Open Finance. EndToEndId no formato BACEN, mensagens
> `pacs.008/002/004` auditadas. ADR 0017.
>
> **Sprint 9 done:** **Antifraude inline no PIX**. Scoring ML síncrono (reusa o
> `fraud-ml`/XGBoost) antes da liquidação SPI; `score >= threshold` → REJEITADO sem
> ir ao SPI. Fail-open, timezone `America/Sao_Paulo`, status `ANALISE_FRAUDE` +
> `score_fraude` persistido. ADR 0018.
>
> **Sprint 10 done:** **Hardening de produção.** (A) Análise pós-liquidação em
> streaming: `pix-api` publica `pix.liquidada` → `Tarifas.Worker` enriquece o
> feature store Redis + alerta de burst. (B) **mTLS na RSFN**: CA self-signed
> (papel da ICP-Brasil), `bacen-sim` exige client cert na 8443, `pix-api` apresenta.
> ADR 0019.

</details>

## Arquitetura do PIX (Sprints 8–10)

```
[Angular/cliente]
    │ POST /api/pix/pagar (JWT)            POST /api/pix/{qrcode,nfc,consentimentos,med}
    ▼
[Pix.Api :5006] ── Clean Arch + CQRS + MediatR ──────────────────────────────┐
    │ 1. resolve chave no DICT ──────────────► [bacen-sim :8443]  (mTLS / RSFN)│
    │ 2. ANTIFRAUDE INLINE (síncrono) ───────► [fraud-ml :5003]   score>=thr?  │
    │      └─ score alto → REJEITADO (não liquida, status ANALISE_FRAUDE)      │
    │ 3. monta pacs.008 → SPI ───────────────► [bacen-sim SPI]    pacs.002 ACSC│
    │ 4. liquida movimentos (D origem / C destino, atômico no Postgres)        │
    │ 5. publica pix.liquidada ──────────────► [Kafka]                         │
    ▼                                              │                           │
[Postgres] pix_pagamento (state machine,           ▼                           │
  pacs.008/002 auditados, score_fraude)     [Tarifas.Worker]  consumer pix     │
                                             └─ enriquece feature store Redis   │
                                                + alerta burst pós-liquidação ──┘
```

**Dois níveis de antifraude:** inline bloqueia na borda (rápido, antes do SPI);
streaming observa na janela (pós-fato, enriquece o modelo p/ os próximos pagamentos).

**mTLS:** os endpoints DICT/SPI do `bacen-sim` só respondem sob HTTPS 8443 com client
cert emitido pela CA. HTTP 8080 fica só pra management (health/metrics/swagger).

## Como rodar (do zero)

```bash
make pyflink-deps     # baixa apache-flink-libraries (220MB) no host — só na 1ª vez
make certs            # gera a cadeia mTLS da RSFN (CA + server + client) — só na 1ª vez
make up               # builda imagens (PyFlink + .NET) e sobe os containers
make seed             # cria Alice (R$500k) e Bob (R$20k)
make e2e              # 7 cenários de transferência: feliz, auto-transf, valor alto, burst, ML, saldo, SSE
make e2e-pix          # 10 fluxos PIX: DICT, ISO 20022, QR, MED, Automático, NFC, Open Finance,
                      #                antifraude inline, streaming pós-liquidação
bash scripts/bench.sh # micro-bench: lat p50/p95 + throughput de N transferências paralelas
```

## Como rodar (1 comando)

```bash
make env            # cria .env (uma vez)
make up             # sobe tudo: postgres + redis + kafka + flink + APIs + worker + auto-approver
make e2e            # valida fluxo end-to-end (Alice → Bob, R$ 200 TED, valida saldos)
```

Acesse:
- **ContaCorrente API**: http://localhost:5000/swagger
- **Transferência API**: http://localhost:5001/swagger
- **PIX API**: http://localhost:5006/swagger
- **bacen-sim** (DICT+SPI): http://localhost:5005/swagger (HTTP mgmt) · https://localhost:5443 (mTLS)
- **Kafka UI**: http://localhost:8080
- **Flink UI**: http://localhost:8082
- **Schema Registry**: http://localhost:8085
- **Grafana**: http://localhost:3000 · **Prometheus**: http://localhost:9090
- **Postgres**: `make psql`
- **Painel ops (SSE)**: `cd frontend && ng serve` → http://localhost:4200/ops/fraude

## Stack

| Camada | Tech |
|---|---|
| Backend | .NET 8 LTS, Clean Arch + CQRS (MediatR), KafkaFlow, Dapper |
| Mensageria | Apache Kafka 7.5 + Zookeeper + Schema Registry (Avro binário) + Kafka UI |
| Streaming | Apache Flink 1.18 / PyFlink — `KeyedProcessFunction` + RocksDB + checkpoint EXACTLY_ONCE |
| ML | XGBoost (ROC-AUC 0.9993) + Flask/Gunicorn — scoring síncrono inline (PIX) e via stream (transf.) |
| PIX | `bacen-sim` (DICT + SPI/ISO 20022 `pacs.008/002/004`), BR Code EMVCo, MED, mTLS na RSFN |
| Banco | PostgreSQL 16 com `NUMERIC(18,2)` em tudo que é dinheiro |
| Cache | Redis 7 — feature store rolling (count_1h, valores_24h/30d) compartilhado transf.+PIX |
| Frontend | Angular 21 standalone (login + dashboard + extrato + transferência + `/ops/fraude` SSE) |
| Observabilidade | Prometheus + Grafana (5 targets, dashboards provisionados) |

## Estrutura

```
contracts/avro/      Schemas Avro dos eventos Kafka (versionados)
infra/compose/       docker-compose.yml unificado (16 serviços)
infra/db/            init.sql (core) + 01-pix.sql (bounded context PIX)
infra/certs/         gen-certs.sh — cadeia mTLS da RSFN (keys no .gitignore)
src/                 Solução .NET — ContaCorrente, Transferencia, Pix, BacenSim, Tarifas.Worker
  BankMore.Pix.*       Domain / Application / Infrastructure / Api (Clean Arch)
  BankMore.BacenSim    Simulador BACEN (DICT + SPI/ISO 20022 + mTLS)
frontend/            Angular standalone
pyflink/             fraud_detector_job.py (PyFlink real, Avro consumer)
ml/                  Treino XGBoost + Flask /predict
scripts/             e2e.sh (transferência) + e2e-pix.sh (10 fluxos PIX) + bench.sh
docs/adr/            19 ADRs (decisões de arquitetura)
```

## Fluxo end-to-end (validado pelo `make e2e`)

```
[Angular :4200]
    │ POST /api/transferencia/efetuar (JWT)
    ▼
[Transferencia.Api :5001]
    │ valida claim cpf, gera id+correlationId
    │ produz JSON em transferencia.solicitada
    ▼
[Kafka :9092] (transferencia.solicitada)
    │
    ▼
[fraud-detector] (Python, state por CPF, regras determinísticas)
    │   R1: cpfOrigem == cpfDestino     → REJEITADA (defesa secundária)
    │   R2: valor <= 0                  → REJEITADA
    │   R3: ≥4 tx/60s mesmo CPF         → REJEITADA (motivo=BURST_*)
    │   R4: valor >= R$ 10.000          → APROVADA + cópia em fraude.alerta
    │   R5: default                     → APROVADA
    │
    ├──▶ transferencia.aprovada   ─────► Tarifas.Worker (consumer-aprovadas) ───┐
    ├──▶ transferencia.rejeitada  ─────► Tarifas.Worker (consumer-rejeitadas)  │
    └──▶ fraude.alerta            ─────► (ops dashboard, Sprint 4)             │
                                                                                │
                                                                                ▼
                                                                       [Tarifas.Worker]
                                                                       Aprovadas:
                                                                         • Tx Postgres ATÔMICA
                                                                         • idempotência por id
                                                                         • mov D origem (valor)
                                                                         • mov D origem (tarifa)
                                                                         • mov C destino (valor)
                                                                         • linha em tarifa (audit)
                                                                         • UPDATE transferencia
                                                                           status='EFETIVADA'
                                                                       Rejeitadas:
                                                                         • UPDATE transferencia
                                                                           status='REJEITADA',
                                                                           motivo, modelo_versao
```

A `transferencia` no Postgres é a fonte de verdade do status:
`SOLICITADA → APROVADA/REJEITADA (decididaEm) → EFETIVADA (efetivadaEm)`.

## O que melhorou vs. versões anteriores

| # | Bug antigo | Status |
|---|---|---|
| 1 | Worker em SQLite, API em Postgres | ✅ ambos Postgres |
| 2 | Frontend chamava endpoint errado | ✅ `TransferenciaService` → 5001 |
| 3 | CPF na URL/body | ✅ extraído do claim JWT |
| 4 | `[Authorize]` ausente | ✅ na classe inteira |
| 5 | `ValidateLifetime = false` | ✅ true em ambas APIs |
| 6 | JWT key hardcoded | ✅ env `JWT_KEY`, min 32 chars, falha se ausente |
| 7 | `REAL` para dinheiro | ✅ `NUMERIC(18,2)` |
| 8 | Tarifa não impacta saldo | ✅ vira movimento `D` categoria=TARIFA |
| 9 | KafkaFlow 3.0 vs 4.1 | ✅ tudo 4.1.0 |
| 10 | `net8` + `net9` misturado | ✅ tudo `net8.0` LTS |
| 11 | Cross-context refs (Conta ↔ Transferência) | ✅ removido |
| 12 | `docker-compose` com `services:` duplicado | ✅ um bloco só |
| 13 | Tópico único `transferencia-realizada` | ✅ `solicitada/aprovada/rejeitada/fraude.alerta` |
| 14 | `ObterExtratoHandler` abria Npgsql direto | ✅ usa `IContaCorrenteRepository` (Clean Arch) |
| 15 | Entity strings para datas (incompat. TIMESTAMPTZ) | ✅ `DateTime` UTC |
| 16 | Dockerfiles desatualizados | ✅ multi-stage SDK 8 + aspnet 8 + healthcheck |
| 17 | Sem `.env` (secrets no JSON) | ✅ `.env` + `.env.example` |
| 18 | Sem teste de integração | ✅ `scripts/e2e.sh` automatizado |
| 19 | `ObterExtratoHandlerTests` quebrado | ✅ 9/9 testes verdes |
| 20 | enum `TipoTransferencia` aceitava só int | ✅ `JsonStringEnumConverter` (PIX/TED/TEF) |

## Sprint 2 + 2.5 + 3 (done)

- ✅ Detector com state (rolling window 60s por CPF) — `pyflink/fraud_detector_job.py` (PyFlink real, em uso)
- ✅ **PyFlink 1.18** com event-time + watermark 5s + RocksDB state + checkpoint EXACTLY_ONCE
- ✅ Persistência da `transferencia.status` no Postgres (SOLICITADA → EFETIVADA/REJEITADA)
- ✅ `RejeicaoConsumer` no Worker fecha o ciclo de status, salva `score_fraude` e `modelo_versao`
- ✅ **ML em produção:** XGBoost embedded em imagem Docker (`ml/Dockerfile` treina no build).
  Flask `/predict` + `/metrics` servidos por Gunicorn. ROC-AUC 0.9993 em dataset sintético.
- ✅ PyFlink chama `/predict` síncrono com **fail-open** (timeout 2s); decisão híbrida regras+score
- ✅ 5 cenários no `make e2e`: feliz, auto-transf, valor alto (ALERTA), burst, **ML rejeita R$ 30k**

### Diagnóstico da virada de chave do PyFlink (anotado pra próxima)

Três problemas em série tiveram que cair pra subir o job:

| Sintoma | Causa real | Solução |
|---|---|---|
| `pip install apache-flink` timeout no daemon Docker | dep `apache-flink-libraries` é 220MB sdist (apache-flink em si é 6MB) | Download no host (`make pyflink-deps`, ~6s @ 32MB/s) + `COPY` no Dockerfile |
| `pemja` falha em "Include folder should be at /opt/java/openjdk/include but doesn't exist" | imagem flink:1.18 tem só JRE, `pemja` compila contra JDK | `apt-get install openjdk-11-jdk-headless` + linkar `jni.h` no JRE |
| `'InternalKeyedProcessFunctionContext' object has no attribute 'output'` | PyFlink 1.18 Python tem bug em side outputs com `KeyedProcessFunction` | `yield` no operator + `.filter()` downstream pra rotear |

## O que ainda não está pronto (produção regulada)

O que sobra exige homologação/infra de produção regulada, não código de demo —
documentado com honestidade nos ADRs:

- ❌ **ICP-Brasil real** — hoje CA self-signed simula a cadeia; produção exige
  certificado A1/A3 de AC credenciada + OCSP/CRL (ADR 0019)
- ❌ **DICT persistente** — `bacen-sim` mantém o diretório em memória (perde no
  restart; registro de chave é idempotente pra mitigar)
- ❌ **Scheduler do PIX Automático com lock distribuído** — hoje single-replica;
  produção usaria Quartz/Hangfire + advisory lock (ADR 0017)
- ❌ **Retreino do modelo com dados PIX** — o XGBoost é agressivo com burst
  (`count_1h >= ~6`), gerando falsos positivos pra PIX (ADR 0018)
- ❌ **PyFlink submetido ao cluster JM/TM externo** — hoje local-mode no container
- ❌ **Frontend do PIX** — a API está completa (Swagger), falta a UI

Itens já entregues nas Sprints 1–10: Avro binário e2e, feature store Redis real,
validação de saldo, Prometheus+Grafana, outbox+DLQ, auth admin, e todo o arranjo
PIX com antifraude em 2 níveis e mTLS.

## Rodar local sem Docker (para dev/debug)

```bash
make build
# Em 4 terminais:
make run-contacorrente
make run-transferencia
make run-worker
make run-approver
make seed     # cria Alice e Bob
make e2e      # valida
```

## Testes

```bash
make test     # 9 testes xUnit, todos passando
```
