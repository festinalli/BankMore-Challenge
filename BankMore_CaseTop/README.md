# BankMore — Real-Time Fraud Detection

Sistema bancário event-driven com detecção de fraude em tempo real.
Toda transferência passa por um detector com state por CPF, regras determinísticas e
3 destinos (aprovada / rejeitada / alerta) **antes** de ser efetivada.

> **Sprint 1 done** (11/05/2026): stack 100% Docker, fluxo Solicitada → Worker.
>
> **Sprint 2 done** (16/05/2026): detector com state, persistência de `SOLICITADA → EFETIVADA/REJEITADA`,
> consumer de rejeições, 4 cenários e2e validados (feliz / auto-transf / valor alto / burst).
> Detector hoje em Python puro (mesma topologia que o job PyFlink seria — wheel apache-flink
> dando timeout no PyPI; swap para PyFlink real fica reservado pra Sprint 4 sem mudar contrato).
>
> ML real e schemas Avro: Sprint 3.

## Como rodar (1 comando)

```bash
cd BankMore_CaseTop
make env            # cria .env (uma vez)
make up             # sobe tudo: postgres + redis + kafka + flink + APIs + worker + auto-approver
make e2e            # valida fluxo end-to-end (Alice → Bob, R$ 200 TED, valida saldos)
```

Acesse:
- **ContaCorrente API**: http://localhost:5000/swagger
- **Transferência API**: http://localhost:5001/swagger
- **Kafka UI**: http://localhost:8080
- **Flink UI**: http://localhost:8082
- **Schema Registry**: http://localhost:8085
- **Postgres**: `make psql`

## Stack

| Camada | Tech |
|---|---|
| Backend | .NET 8 LTS, KafkaFlow 4.1, Dapper |
| Mensageria | Apache Kafka 7.5 + Zookeeper + Schema Registry + Kafka UI |
| Streaming | Apache Flink 1.18 (placeholder p/ Sprint 2 — hoje `auto_approver.py`) |
| Banco | PostgreSQL 16 com `NUMERIC(18,2)` em tudo que é dinheiro |
| Cache | Redis 7 (feature store para o ML — Sprint 3) |
| Frontend | Angular 21 standalone (login + dashboard + extrato + transferência) |
| Observabilidade | Prometheus + Grafana + OTEL — Sprint 4 |

## Estrutura

```
contracts/avro/      Schemas Avro dos eventos Kafka (versionados)
infra/compose/       docker-compose.yml unificado
infra/db/init.sql    Schema canônico Postgres
src/                 Solução .NET (6 projetos + tests)
frontend/            Angular standalone
pyflink/             auto_approver.py (Sprint 1) → fraud_detection_job.py (Sprint 2)
ml/                  Treino e Flask (Sprint 3)
scripts/e2e.sh       Validação automática do fluxo
tests/               xUnit dos handlers
docs/                Storyline de entrevista
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

## Sprint 2 (done)

- ✅ Detector com state (rolling window 60s por CPF) — `pyflink/fraud_detector.py`
- ✅ Persistência da `transferencia.status` no Postgres (SOLICITADA → EFETIVADA/REJEITADA)
- ✅ `RejeicaoConsumer` no Worker fecha o ciclo de status
- ✅ 4 cenários no `make e2e`: feliz, auto-transf, valor alto (ALERTA), burst (BURST_*)

**Pivot de Sprint 2 (assumido):** o wheel `apache-flink` (~350MB) deu read-timeout
consistentemente no PyPI. Implementei o detector em Python puro com a **mesma topologia
e contrato** que o job PyFlink teria. O swap futuro é local — não muda eventos nem
consumers. Estrutura PyFlink (`fraud_detector_job.py`, `Dockerfile.flink`) versionada
para uso no Sprint 4.

## O que ainda não está pronto (Sprints 3+)

- ❌ PyFlink real (job em RocksDB + checkpoint exactly-once + Async I/O para ML)
- ❌ Avro + Schema Registry — Sprint 2 ainda usa JSON
- ❌ Modelo de ML treinado (`ml/train.ipynb`)
- ❌ Validação de saldo (transferir mais que tem ainda passa — Worker debita negativo)
- ❌ PasswordHasher PBKDF2 (hoje SHA-256)
- ❌ Validação de CPF com dígitos verificadores
- ❌ Painel ops `/ops/fraude` no frontend
- ❌ Prometheus + Grafana + Jaeger
- ❌ Frontend ainda fora do compose (rodar `cd frontend && ng serve` manual)
- ❌ Outbox pattern para garantir atomicidade entre persistir e publicar

Mapeado em [`CASE_TOP_PLAN.md`](CASE_TOP_PLAN.md).

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
