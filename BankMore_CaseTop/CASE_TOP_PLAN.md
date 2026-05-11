# BankMore Case Top — Plano de Implementação

> Roadmap consolidado. Implementação inicia **2026-05-14 (quinta)**.

## 0. Pitch

Sistema bancário event-driven onde **toda transferência passa por um pipeline PyFlink antes de ser efetivada**. Decisão em < 1s, modelo de ML real, observabilidade ponta-a-ponta, demo ao vivo de ataque sendo bloqueado.

## 1. Arquitetura alvo

```
              ┌─────────────────────────────────────────────┐
              │  Angular 18 (4200)                          │
              │  • dashboard cliente                        │
              │  • painel ops (alertas via SSE)             │
              └──────────────┬──────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────────┐
        │                    │                        │
┌───────▼──────┐   ┌─────────▼────────┐   ┌───────────▼────────┐
│ ContaCorr.   │   │ Transferencia    │   │ Fraud-Ops API      │
│ Api (5000)   │   │ Api (5001)       │   │ (5004)             │
│ saldo/extr.  │   │ POST /efetuar    │   │ list/replay alertas│
└──────┬───────┘   └─────────┬────────┘   └───────────┬────────┘
       │                     │                        │
       │ Debezium CDC        │ produz Avro            │
       ▼                     ▼                        │
╔═══════════════════════════════════════════════════════════════╗
║                       APACHE KAFKA                           ║
║  transferencia.solicitada → transferencia.{aprovada,rejeit.} ║
║  fraude.alerta                                               ║
╚═══════════│═════════════════════════│═════════════════════════╝
            │                         │
            ▼                         ▼
    ┌───────────────────┐   ┌──────────────────────┐
    │   PyFlink 1.18    │   │ Tarifas.Worker (.NET)│
    │ event-time + WM   │   │ consume "aprovada"   │
    │ KeyedState 1h/CPF │   │ → débito/crédito/    │
    │ Async I/O ML      │   │   tarifa atômicos    │
    │ side outputs:     │   └──────────────────────┘
    │  aprovada/rejeit/ │           ▲
    │  alerta           ├───────────┘
    └────────┬──────────┘
             │
             ▼
    ┌───────────────────┐
    │ ML Service (Py)   │
    │ Flask + Gunicorn  │
    │ IsolationForest   │
    │ + XGBoost         │
    │ Redis features    │
    └───────────────────┘

    Prometheus + Grafana + Jaeger orquestrando tudo
```

**Mudança crítica vs. versões anteriores:** o tópico de saída da API de Transferência é `transferencia.solicitada`. O Worker **não** consome isso — ele só consome `transferencia.aprovada`. Quem decide é o PyFlink, em side output. Fraude deixa de ser "alerta posterior" e vira **autorização sincrônica via stream**, padrão de fintech real.

## 2. Roadmap

### Sprint 1 — Contrato único + plumbing (1-2 dias)

- [ ] Avro Schema Registry, schema `TransferenciaSolicitada.avsc` versionado
- [ ] API .NET passa a publicar Avro (Confluent.SchemaRegistry)
- [ ] PyFlink lê Avro com `AvroDeserializationSchema`
- [ ] `docker-compose.yml` reescrito do zero (1 bloco, sem duplicação)
- [ ] APIs .NET + Worker + Schema Registry + Kafka UI no compose
- [ ] Worker consome **só** `transferencia.aprovada`
- [ ] Postgres com `NUMERIC(18,2)` em todas as colunas de dinheiro

**Saída:** evento end-to-end de "request → solicitada → (decide manual via Kafka UI) → aprovada → Worker debita".

### Sprint 2 — PyFlink "para valer" (2-3 dias)

- [ ] `enableCheckpointing(60_000)` + `EXACTLY_ONCE` + RocksDB state backend
- [ ] Event-time + `WatermarkStrategy.forBoundedOutOfOrderness(5s)`
- [ ] `KeyedProcessFunction` com `MapState<long, Transaction>` para janela 1h por CPF (sem Redis para state)
- [ ] Async I/O para ML scoring (batch + aiohttp ou modelo embedado via joblib)
- [ ] Side outputs: aprovada / rejeitada / alerta
- [ ] Métricas Prometheus expostas (`flink-metrics-prometheus`)

**Saída:** PyFlink decidindo sozinho, mock do ML retornando score fixo.

### Sprint 3 — ML real (1-2 dias)

- [ ] Dataset sintético (Faker + power-law em valores; ~2% de fraude injetada)
- [ ] Notebook `train.ipynb`:
  1. Feature engineering (rolling stats, time-of-day, tipo, distância CPF↔CPF)
  2. Baseline IsolationForest
  3. XGBoost com `class_weight` (recall focal)
  4. Serialização `model.joblib` + `feature_pipeline.joblib`
- [ ] Flask `app.py`:
  - `POST /predict` recebe features pré-computadas, retorna `{score, model_version, latency_ms}`
  - `GET /metrics` Prometheus
- [ ] Versionar modelo via header `X-Model-Version` no Kafka (rastreabilidade)

**Saída:** decisões com ML real, métricas de latência e drift visíveis.

### Sprint 4 — UX + storytelling (1 dia)

- [ ] Painel Angular `/ops/fraude` consumindo SSE de `fraude.alerta` e `transferencia.rejeitada`
- [ ] Cards: tps, % rejeitadas (1h), valor bloqueado, p95 decisão
- [ ] Cliente vê "transferência em análise" → "aprovada/rejeitada" via long-poll do `correlationId`
- [ ] Grafana dashboard pré-configurado no compose
- [ ] Script `make demo`:
  1. Sobe tudo
  2. Cria 5 contas seed
  3. Roda 50 transferências legítimas
  4. Injeta burst de 8 transferências de R$4.999 do mesmo CPF em 30s
  5. Pipeline rejeita a partir da 4ª — visível no Grafana ao vivo

**Saída:** demo gravável, repo pronto para LinkedIn.

## 3. Storyline da entrevista (4 min)

1. **Problema:** banco precisa decidir em < 1s, regras simples não pegam fracionamento/burst.
2. **Decisão #1 — event-driven:** API só *solicita*; resposta 202 + protocolo; cliente recebe push depois. *Tradeoff: complexidade de UX por escalabilidade.*
3. **Decisão #2 — Flink síncrono no path crítico:** state por CPF, janela 1h, exactly-once. *Tradeoff: ops vs ganho de stateful processing.*
4. **Decisão #3 — ML híbrido:** regras duras (saldo, autotransferência) no Flink + score do modelo no Flask. *Tradeoff: latência HTTP vs versionar modelo separado.*
5. **Demo ao vivo** com Grafana mostrando ataque sendo bloqueado.
6. **Métricas medidas:** throughput X tps, p95 Y ms, recall Z em fraude sintética.
7. **Pontos de evolução já mapeados** (diferencial sênior): schema evolution, retraining via Airflow, multi-region Kafka, LGPD para CPF, shadow mode para A/B online.

## 4. Pontos extras de impacto

- **Idempotência por evento:** `correlationId` em Kafka header propagado em todo pipeline; Worker faz `INSERT ... ON CONFLICT DO NOTHING`.
- **Saga com compensation:** 3 falhas no débito → emite `transferencia.compensada`, ML aprende.
- **Feature store mínima:** Redis (TTL) + Postgres como warm store; modelo declara features que precisa.
- **Shadow mode:** Flink chama dois modelos, registra ambas predições, só uma decide. A/B online sem risco.
- **Property-based testing** com Hypothesis no scoring.
- **OpenTelemetry** ponta-a-ponta: trace completa Angular → API → Kafka → Flink → ML → Worker → Postgres no Jaeger.
- **Privacidade:** CPF mascarado em logs; pseudonimização nos eventos via `hash(CPF, salt_rotativo)`.

## 5. Bugs herdados que precisam morrer no Sprint 1

| # | Bug | Origem |
|---|---|---|
| 1 | `docker-compose.yml` com `services:` duplicado | BankFest_Fink |
| 2 | API .NET produz Newtonsoft PascalCase, PyFlink espera camelCase | toda |
| 3 | PyFlink chama `/predict`, Flask expõe `/api/fraude/analisar` | BankFest_Fink |
| 4 | Worker em SQLite, API em Postgres (DBs desconectados) | Corrigido |
| 5 | Frontend chama `/api/contacorrente/movimentar` em vez de transferência | Corrigido |
| 6 | Endpoints sem `[Authorize]`; CPF na URL/body em vez do JWT | toda |
| 7 | `ValidateLifetime = false` na Transferência API | toda |
| 8 | PasswordHasher SHA-256 simples + salt 8 chars | toda |
| 9 | `Random()` para número de conta sem checar UNIQUE | toda |
| 10 | `REAL` para dinheiro em vez de `NUMERIC(18,2)` | Corrigido |
| 11 | Tarifa não vira movimento → saldo errado | toda |
| 12 | Sem validação de saldo na transferência | toda |
| 13 | Sem retry/DLQ no Kafka, sem idempotência no Worker | toda |
| 14 | KafkaFlow 3.0 producer + 4.1 consumer (incompat) | toda |
| 15 | JWT key hardcoded no código + `appsettings.json` | toda |

## 6. Definition of Done

- [ ] `docker-compose up` sobe **tudo**, sem ação manual extra.
- [ ] `make demo` executa o roteiro do Sprint 4 sem intervenção.
- [ ] Cobertura de testes ≥ 70% nos handlers .NET, ≥ 60% no PyFlink (via mini-cluster).
- [ ] README com diagrama, comandos, e link para vídeo de 2 min da demo.
- [ ] Repo público no GitHub com tags semânticas por sprint.
