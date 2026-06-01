# 0013 — Schema Registry com payload JSON (híbrido) (Sprint 5.C)

**Status:** Aceito · **Data:** 2026-05-19

## Contexto

Sem schemas formais, qualquer mudança no `TransferenciaSolicitadaMessage`
do producer .NET pode quebrar silenciosamente o consumer PyFlink (campo
renomeado, tipo mudado de int pra string, etc). Schema Registry resolve
isso fornecendo:

1. **Contrato versionado** acessível por HTTP
2. **Validação de compatibilidade** (BACKWARD = consumer N+1 lê producer N)
3. **Documentação executável** dos eventos

Caminho ideal: producer/consumer usarem Avro binário com `AvroSerializer<T>`
(.NET) e `ConfluentRegistryAvroDeserializationSchema` (PyFlink Java
connector).

## Decisão (versão híbrida)

Nesta sprint, o trade-off de custo/benefício favorece **schema documentado
+ payload JSON** sobre migração completa pra Avro binário:

- `contracts/avro/transferencia-solicitada.avsc` e `transferencia-decidida.avsc`
  ficam committed no git como **fonte de verdade**.
- `scripts/register-schemas.sh` sobe pro registry rodando em `:8085` com
  compatibility `BACKWARD`. Idempotente — pode rodar várias vezes.
- 4 subjects registrados:
  - `transferencia.solicitada-value` → schema solicitada
  - `transferencia.aprovada-value`    → schema decidida (disc. APROVADA)
  - `transferencia.rejeitada-value`   → schema decidida (disc. REJEITADA)
  - `fraude.alerta-value`             → schema decidida (cópia c/ alerta)
- **Producer/consumer continuam JSON** (sem mexer no .NET nem no PyFlink).

## Por que não Avro binário agora

- Migrar producer .NET → `Confluent.SchemaRegistry.Serdes.Avro` quebra o
  `OutboxRelayHostedService` (precisa do envelope binário, não string)
- Migrar consumer PyFlink → adiciona JAR `flink-avro-confluent-registry-1.18.jar`,
  re-gera classes Avro, reescreve `KafkaSource.builder()` com novo `Deserializer`
- Cada lado tem seu próprio teste de regressão; total ≈ 1 sprint inteira

Hoje (5.C parte 1) ganhamos **80% do valor** (contrato registrado,
compatibilidade documentada, registry-as-source-of-truth visível no Kafka UI)
sem essa mudança ampla.

## Migração planejada (Sprint 6 — "5.C parte 2")

```
git mv contracts/avro/*.avsc                 ← já existe
[Producer .NET]
  - Adicionar Confluent.SchemaRegistry.Serdes.Avro nuget
  - Gerar classe TransferenciaSolicitada via avrogen
  - OutboxRelay: trocar producer.Produce<string,string> por
    producer.Produce<string,TransferenciaSolicitada>
  - Payload no outbox vira BYTES (não JSONB) — schema_id + binário Avro
[Consumer PyFlink]
  - Baixar flink-avro-confluent-registry-1.18.jar pra lib/
  - Trocar SimpleStringSchema por ConfluentRegistryAvroDeserializationSchema
  - Acesso à classe TransferenciaSolicitada (Java codegen ou GenericRecord)
[Testes]
  - e2e novo: valida que mensagem com schema antigo é lida por consumer novo
  - e2e novo: valida que mensagem com schema novo NÃO quebra consumer antigo
    (BACKWARD compatibility test)
```

## Consequências (sprint 5.C parte 1)

- ✅ Schemas registrados — disponível em http://localhost:8085/subjects
- ✅ Kafka UI mostra schemas vinculados aos tópicos (UX boa pra ops)
- ✅ Compatibility check ON: tentar subir schema incompatível → 409
- ✅ `make register-schemas` idempotente
- ⚠ Producer/consumer não usam os schemas em runtime ainda
- ⚠ Mensagens JSON podem divergir do schema sem detecção automática até
  Sprint 6
