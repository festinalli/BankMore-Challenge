# BankMore — Real-Time Fraud Detection

Sistema bancário event-driven com detecção de fraude em tempo real via PyFlink.
Toda transferência passa por um pipeline de scoring antes de ser efetivada — decisão sub-segundo, modelo de ML treinado, observabilidade ponta-a-ponta.

> **Sprint 1 — done (11/05/2026):** base .NET refatorada, Postgres canônico, Kafka com tópicos novos, frontend Angular consumindo APIs corretas, auto-approver Python no lugar do Flink real (entra no Sprint 2).
> Veja [`CASE_TOP_PLAN.md`](CASE_TOP_PLAN.md) para o roadmap completo.

## Stack

- **.NET 8 LTS** — APIs ContaCorrente + Transferência + Worker (KafkaFlow 4.1)
- **Apache Kafka 7.5** + Schema Registry + Kafka UI
- **PyFlink 1.18** — entra no Sprint 2 (hoje: `auto_approver.py` placeholder)
- **scikit-learn / XGBoost** — Sprint 3
- **Postgres 16** com `NUMERIC(18,2)` em tudo que é dinheiro
- **Redis 7** — feature store
- **Angular 18** — frontend
- **Prometheus + Grafana + OpenTelemetry** — Sprint 4

## Estrutura

```
contracts/avro/     Schemas Avro versionados dos eventos Kafka
infra/compose/      docker-compose.yml unificado
infra/db/init.sql   Schema canônico (NUMERIC(18,2), view saldo_conta)
src/                Solução .NET (.csproj em net8.0)
frontend/           Angular standalone (login, dashboard, extrato, transferência)
pyflink/            auto_approver.py (Sprint 1) → fraud_detection_job.py (Sprint 2)
ml/                 Treino e serviço Flask (Sprint 3)
tests/              xUnit dos handlers
docs/               Documentação técnica e storyline
```

## Como rodar (Sprint 1)

```bash
# 1) Sobe infra (Postgres, Redis, Kafka stack, Flink)
make up

# 2) Em 3 terminais separados:
make run-contacorrente     # http://localhost:5000/swagger
make run-transferencia     # http://localhost:5001/swagger
make run-worker            # consumer transferencia.aprovada

# 3) Auto-approver (Sprint 1 only — vai morrer no Sprint 2)
make run-approver

# 4) Seed de 5 contas (senha "senha123" pra todas)
make seed

# 5) Frontend
cd frontend && npm install && ng serve
# http://localhost:4200
```

Acesse:
- Kafka UI: http://localhost:8080
- Flink UI: http://localhost:8082
- Schema Registry: http://localhost:8085
- Postgres: `make psql`

## Fluxo end-to-end (Sprint 1)

```
Angular (4200) → POST /api/transferencia/efetuar
                 ↓ JWT obrigatório, CPF origem vem do claim
                 Transferencia.Api (5001)
                 ↓ produz transferencia.solicitada
                 Kafka (9092)
                 ↓
                 auto_approver.py (Python)         ← Sprint 2 substitui pelo PyFlink real
                 ↓ produz transferencia.aprovada
                 Kafka (9092)
                 ↓
                 Tarifas.Worker
                 ↓ transação Postgres ATÔMICA:
                   - movimento D (valor) na origem
                   - movimento D (tarifa) na origem  ← saldo agora reflete tarifa!
                   - movimento C (valor) no destino
                   - linha em tarifa (auditoria)
                   - atualiza transferencia.status='EFETIVADA'
                   - registra idempotência por id da transferência
                 Postgres (5432)
```

## O que melhorou em relação às versões anteriores

| # | Bug antigo | Status |
|---|---|---|
| 1 | Worker em SQLite, API em Postgres | ✅ ambos em Postgres |
| 2 | Frontend chamava endpoint errado | ✅ `TransferenciaService` → 5001 |
| 3 | CPF na URL/body | ✅ extraído do claim JWT |
| 4 | `[Authorize]` ausente | ✅ na classe inteira |
| 5 | `ValidateLifetime = false` | ✅ true em ambas APIs |
| 6 | JWT key hardcoded | ✅ env var `JWT_KEY`, min 32 chars |
| 7 | `REAL` para dinheiro | ✅ `NUMERIC(18,2)` |
| 8 | Tarifa não impacta saldo | ✅ vira movimento `D` categoria=TARIFA |
| 9 | KafkaFlow 3.0 vs 4.1 | ✅ tudo 4.1.0 |
| 10 | `net8` + `net9` misturado | ✅ tudo `net8.0` LTS |
| 11 | Cross-context refs (Conta ↔ Transferência) | ✅ removido |
| 12 | `docker-compose` com `services:` duplicado | ✅ um bloco só |
| 13 | Tópico `transferencia-realizada` único | ✅ `solicitada`/`aprovada`/`rejeitada`/`fraude.alerta` |

## O que ainda não está pronto (Sprint 2+)

- ❌ PyFlink real (job de detecção com state, watermarks, async ML)
- ❌ Avro + Schema Registry — Sprint 1 usa JSON
- ❌ ML treinado de fato
- ❌ ContaCorrente.Application/`ObterExtratoQuery.cs` ainda abre Npgsql direto (não usa `IContaCorrenteRepository.ObterMovimentos`)
- ❌ Validação de saldo (transferir mais que tem ainda passa)
- ❌ PasswordHasher SHA-256 puro — migrar para PBKDF2
- ❌ Validação de CPF com dígitos verificadores
- ❌ Dockerfiles atualizados para as APIs .NET (rodar tudo no compose)
- ❌ Testes do `ObterExtratoHandler` quebrados (handler abre conexão real)

Tudo isso está endereçado em [`CASE_TOP_PLAN.md`](CASE_TOP_PLAN.md).
