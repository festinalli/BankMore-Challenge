# Arquitetura — BankMore (modelo C4)

Sistema bancário event-driven com **PIX real** (DICT, ISO 20022, MED, QR EMVCo,
PIX Automático, NFC, Open Finance), **mTLS na RSFN** e **detecção de fraude em
tempo real** (PyFlink + XGBoost) em **dois níveis** (inline + streaming).

Stack: **.NET 8** · **PyFlink 1.18** · **XGBoost** · **Kafka** · **Redis** ·
**PostgreSQL 16** · **Angular 21** · **Prometheus/Grafana** · **Docker Compose**.

---

## C4 — Nível 1: Contexto do Sistema

```mermaid
C4Context
    title Contexto — BankMore

    Person(cliente, "Cliente", "Correntista — faz transferências e PIX via app/API")
    Person(ops, "Operador (Ops)", "Monitora fraude e DLQ em tempo real")

    System(bankmore, "BankMore", "Sistema bancário event-driven: contas, transferências, PIX real e antifraude")

    System_Ext(bacen, "BACEN — DICT + SPI", "Diretório de chaves (DICT) e liquidação ISO 20022 (SPI). Acesso via mTLS na RSFN. [simulado por bacen-sim]")
    System_Ext(tpp, "Open Finance / TPP", "Iniciador de pagamento por terceiro")

    Rel(cliente, bankmore, "Autentica, transfere, paga PIX", "HTTPS/JWT")
    Rel(ops, bankmore, "Acompanha alertas de fraude", "SSE")
    Rel(bankmore, bacen, "Resolve chave + liquida", "mTLS / ISO 20022")
    Rel(tpp, bankmore, "Inicia pagamento via consentimento", "HTTPS")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

---

## C4 — Nível 2: Containers

```mermaid
C4Container
    title Containers — BankMore

    Person(cliente, "Cliente", "App/API")
    Person(ops, "Ops", "Dashboard")
    System_Ext(bacen, "bacen-sim", "DICT + SPI (mTLS)")

    Container_Boundary(bm, "BankMore") {
        Container(spa, "Frontend", "Angular 21", "Login, extrato, transferência, painel ops (SSE)")

        Container(conta, "ContaCorrente.Api", ".NET 8", "Auth JWT, contas, saldo, /ops/fraude (SSE)")
        Container(transf, "Transferencia.Api", ".NET 8", "Transferências + Outbox Relay (Postgres→Kafka)")
        Container(pix, "Pix.Api", ".NET 8", "PIX: pagamento, QR, MED, Automático, NFC, OF + antifraude inline + scheduler")
        Container(worker, "Tarifas.Worker", ".NET 8", "Efetiva transferências, tarifas, feature store + análise pós-liquidação PIX")

        Container(detector, "fraud-detector", "PyFlink 1.18", "Regras + ML em tempo real; KeyedState + checkpoint EXACTLY_ONCE")
        Container(ml, "fraud-ml", "Flask + XGBoost", "/predict — scoring (ROC-AUC 0.9993)")

        ContainerDb(pg, "PostgreSQL 16", "RDBMS", "Contas, movimentos, transferências, outbox, PIX, consentimentos")
        ContainerDb(redis, "Redis 7", "Cache", "Feature store rolling (count_1h, valores_24h/30d)")
        ContainerQueue(kafka, "Kafka + Schema Registry", "Event bus", "solicitada/aprovada/rejeitada, fraude.alerta, pix.liquidada (Avro)")
    }

    System_Ext(prom, "Prometheus + Grafana", "Observabilidade", "Métricas dos 5 targets + dashboards")

    Rel(cliente, spa, "Usa", "HTTPS")
    Rel(spa, conta, "Login/saldo", "REST/JWT")
    Rel(spa, transf, "Transfere", "REST/JWT")
    Rel(spa, pix, "PIX", "REST/JWT")
    Rel(ops, conta, "Stream de alertas", "SSE")

    Rel(transf, pg, "Grava transf + outbox (1 TX)")
    Rel(transf, kafka, "Publica transferencia.solicitada (Avro)")
    Rel(kafka, detector, "Consome solicitada")
    Rel(detector, ml, "Scoring síncrono", "HTTP")
    Rel(detector, kafka, "aprovada / rejeitada / alerta")
    Rel(kafka, worker, "Consome aprovada + pix.liquidada")
    Rel(worker, pg, "Efetiva (movimentos)")
    Rel(worker, redis, "Atualiza feature store")
    Rel(ml, redis, "Lê features")

    Rel(pix, bacen, "Resolve chave + liquida", "mTLS/ISO 20022")
    Rel(pix, ml, "Antifraude inline (síncrono)", "HTTP")
    Rel(pix, pg, "State machine + auditoria ISO")
    Rel(pix, kafka, "Publica pix.liquidada")

    Rel(prom, conta, "scrape /metrics")
    Rel(prom, detector, "scrape :9249 (Flink reporter)")
```

---

## Fluxo PIX — pagamento por chave (com antifraude em 2 níveis)

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente
    participant PIX as Pix.Api
    participant DICT as bacen-sim (DICT)
    participant ML as fraud-ml
    participant SPI as bacen-sim (SPI)
    participant DB as Postgres
    participant K as Kafka
    participant W as Tarifas.Worker
    participant R as Redis

    C->>PIX: POST /api/pix/pagar (chave, valor) JWT
    PIX->>DICT: resolve chave (mTLS)
    DICT-->>PIX: ISPB + titular
    Note over PIX: regra dura: auto-transferência? valor<=0?
    PIX->>ML: scoring inline (síncrono)
    ML-->>PIX: score
    alt score >= threshold
        PIX-->>C: 422 REJEITADO (ANALISE_FRAUDE) — não liquida
    else aprovado
        PIX->>SPI: pacs.008 (mTLS / ISO 20022)
        SPI-->>PIX: pacs.002 ACSC
        PIX->>DB: liquida (D origem / C destino, atômico) + auditoria ISO
        PIX-->>C: 200 LIQUIDADO (e2eId)
        PIX->>K: publica pix.liquidada
        K->>W: consome (pós-liquidação)
        W->>R: enriquece feature store + alerta burst
    end
```

---

## Fluxo Transferência — fraud detection em streaming

```mermaid
flowchart LR
    A[Transferencia.Api] -->|outbox 1 TX| DB[(Postgres)]
    A -->|Avro| K[(Kafka<br/>transferencia.solicitada)]
    K --> F[fraud-detector<br/>PyFlink + KeyedState]
    F -->|features| ML[fraud-ml<br/>XGBoost]
    ML -->|enriquece| R[(Redis<br/>feature store)]
    F -->|APROVADA| K2[(transferencia.aprovada)]
    F -->|REJEITADA| K3[(transferencia.rejeitada)]
    F -->|ALERTA| K4[(fraude.alerta)]
    K2 --> W[Tarifas.Worker]
    W -->|D origem / C destino| DB
    W -->|count_1h, valores| R
    K4 --> SSE[/ops/fraude SSE/]
```

---

## Infra (Docker Compose — 16 serviços)

| Grupo | Serviços | Portas |
|---|---|---|
| **APIs .NET** | contacorrente-api, transferencia-api, pix-api, bacen-sim | 5000 / 5001 / 5006 / 5005·5443(mTLS) |
| **Worker / ML** | tarifas-worker, fraud-ml | 9102(metrics) / 5003 |
| **Streaming** | fraud-detector (PyFlink), flink-jobmanager, flink-taskmanager | 9249 / 8082 |
| **Mensageria** | kafka, zookeeper, schema-registry, kafka-ui | 9092 / 8085 / 8080 |
| **Dados** | postgres, redis | 5432 / 6379 |
| **Observabilidade** | prometheus, grafana | 9090 / 3000 |

**Segurança:** JWT (PBKDF2) · mTLS na RSFN (CA → bacen-sim/pix-api) · auth admin fail-closed.
**Resiliência:** Outbox + DLQ · idempotência · fail-open no ML · checkpoint EXACTLY_ONCE.
**Qualidade:** `make e2e` (7 cenários) + `make e2e-pix` (10 fluxos) · 19 ADRs.
