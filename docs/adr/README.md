# ADRs — Architecture Decision Records

Decisões arquiteturais relevantes do BankMore Case Top. Cada ADR captura o
**contexto**, a **decisão** e as **consequências** — incluindo tradeoffs e o
que descartamos.

Formato: [MADR-lite](https://adr.github.io/madr/) (Markdown Any Decision Record).
Status: `Aceita` (em uso), `Substituída` (deprecated), `Proposta` (em discussão).

## Índice

| ID | Decisão | Status |
|---|---|---|
| [0001](0001-bounded-contexts.md) | Bounded contexts ContaCorrente e Transferência separados | Aceita |
| [0002](0002-cqrs-mediatr.md) | CQRS + MediatR como padrão de orquestração | Aceita |
| [0003](0003-pyflink-real.md) | PyFlink real (não Python puro) — event-time + RocksDB + EXACTLY_ONCE | Aceita |
| [0004](0004-ml-fail-open.md) | Fail-open no ML scoring (não bloqueia transferências se /predict cair) | Aceita |
| [0005](0005-sse-vs-websocket.md) | Painel ops via SSE (não WebSocket) | Aceita |
| [0006](0006-parallelism-3.md) | PyFlink parallelism=3 (match com partitions) | Aceita |
| [0007](0007-zoneless-signals.md) | Angular zoneless + signals (substitui Zone.js) | Aceita |
| [0008](0008-pbkdf2.md) | PBKDF2-HMAC-SHA256 100k iterações para senhas | Aceita |
| [0009](0009-exception-middleware.md) | Global exception middleware (não try/catch repetitivo) | Aceita |
| [0010](0010-rate-limit-sse.md) | Rate limit por IP + cap global no SSE | Aceita |

## Decisões pendentes (Sprint 5+)

| ID | Tema | Por que ainda não |
|---|---|---|
| — | **Outbox pattern** na Transferência.Api | Refator com risco — exige tabela `outbox_event` + relay worker. Hoje persistimos e publicamos sequencial: race em crash, mas baixa probabilidade pro escopo de case. |
| — | **Avro + Schema Registry** | Schema Registry está no compose mas tópicos seguem com JSON livre. Migração quebra back-compat. |
| — | **OpenTelemetry + traceparent W3C** | `correlationId` já existe; falta propagar como `traceparent` pra abrir Jaeger end-to-end. |
| — | **Prometheus + Grafana** | `/metrics` no ML retorna JSON, APIs não expõem nada. Adapter `prometheus-net.AspNetCore` + `prometheus_client` resolve. |
| — | **Argon2id** | Hoje PBKDF2 (nativo .NET). Argon2id é estado da arte mas exige `Konscious.Security.Cryptography` (NuGet externa). |
| — | **DLT (Dead Letter Topic)** | KafkaFlow tem retry default mas zero DLT. Mensagem envenenada → loop infinito. |
