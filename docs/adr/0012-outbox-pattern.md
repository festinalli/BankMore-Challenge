# 0012 — Outbox pattern para publicação Kafka (Sprint 5.B)

**Status:** Aceito · **Data:** 2026-05-19

## Contexto

Até Sprint 4.B o `EfetuarTransferenciaHandler` fazia:

```
1. INSERT INTO transferencia (status='SOLICITADA') -- commit
2. producer.ProduceAsync(...)                       -- pode falhar
```

Race: se o producer falhar (Kafka indisponível, broker reiniciando,
rede), a transferência fica órfã com status `SOLICITADA` no Postgres —
**fantasma**. O cliente recebe `202 Accepted` mas o pipeline nunca
processa. Nenhuma compensação automática.

Padrão clássico pra resolver: **Outbox**.

## Decisão

Tabela `transferencia_outbox` no Postgres:

```sql
CREATE TABLE transferencia_outbox (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transferencia_id    TEXT NOT NULL REFERENCES transferencia(id),
    topic               TEXT NOT NULL,
    payload             JSONB NOT NULL,
    criado_em           TIMESTAMPTZ DEFAULT NOW(),
    publicado_em        TIMESTAMPTZ,
    tentativas          INTEGER DEFAULT 0,
    ultima_tentativa_em TIMESTAMPTZ,
    ultimo_erro         TEXT
);

CREATE INDEX ix_outbox_pendente ON transferencia_outbox (criado_em)
    WHERE publicado_em IS NULL;  -- index parcial: relay só varre não-publicados
```

Handler agora:

```
BEGIN
  INSERT INTO transferencia          (status='SOLICITADA')
  INSERT INTO transferencia_outbox   (payload=json(message))
COMMIT
```

Em outro processo, `OutboxRelayHostedService` (BackgroundService dentro
da própria `Transferencia.Api`):

```
poll a cada 500ms:
  SELECT ... FROM transferencia_outbox
    WHERE publicado_em IS NULL
      AND (ultima_tentativa_em IS NULL OR ultima_tentativa_em < NOW() - INTERVAL '5s' * tentativas)
    ORDER BY criado_em LIMIT 50
    FOR UPDATE SKIP LOCKED
  Para cada row:
    producer.Produce(topic, payload)   # acks=all, idempotence=true
    sucesso → UPDATE publicado_em
    falha   → UPDATE tentativas++, ultimo_erro
```

`FOR UPDATE SKIP LOCKED` permite escalar pra **N réplicas** sem race —
cada uma pega lotes distintos. Backoff exponencial (5s × tentativas) entre
retries.

## Por que `HostedService` na mesma API (e não worker .NET separado)

- Mesmo pool de connection já configurado, sem duplicar setup
- 1 réplica é suficiente; `FOR UPDATE SKIP LOCKED` cobre o caso multi-replica
- Se a API cair, ninguém publica — mas a API **é o único produtor mesmo**,
  então quando ela voltar, o relay drena o outbox naturalmente

## Por que JSON no payload (não Avro ainda)

Sprint 5.C registra os schemas Avro no Schema Registry, mas o payload
publicado **continua JSON** nesta versão. Migração pra Avro binário fica
como Sprint 6 (precisa mexer no producer .NET, no PyFlink consumer e nos
testes — escopo grande). Os schemas no registry servem como contrato
documentado e basecamp pra migração.

## Consequências

- ✅ Atomicidade Postgres↔Kafka garantida (mesma TX)
- ✅ Producer fora do path crítico da API — resposta `202` instantânea
- ✅ Retries com backoff exponencial sem flood
- ✅ Observabilidade via 3 métricas Prometheus: `bankmore_outbox_publicados_total`,
  `bankmore_outbox_falhas_total`, `bankmore_outbox_lote_size`
- ⚠ Latência adicional ≈ 250ms entre commit e publicação (metade do poll
  interval). Aceito; não impacta o cliente (assíncrono mesmo).
- ⚠ Sem DLQ ainda: depois de N tentativas a row fica órfã com `tentativas`
  alto. Sprint 6 deve adicionar política de DLQ + alerta.
- ⚠ KafkaFlow producer removido do `Transferencia.Api`; trocado por
  `Confluent.Kafka` direto no relay (`acks=all`, `enable.idempotence=true`).
