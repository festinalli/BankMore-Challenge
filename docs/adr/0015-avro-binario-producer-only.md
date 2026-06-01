# 0015 — Avro binário só no producer .NET (Sprint 6.B)

**Status:** Parcialmente aceito · **Data:** 2026-05-19

## Contexto

ADR 0013 deixou o plano de migração JSON → Avro binário pendente. Sprint 6.B
ataca essa migração no canal mais crítico: `transferencia.solicitada`.

Avro binário no wire format Confluent: `magic byte (0x00) + schema_id (4
bytes big-endian) + bytes Avro do payload`. Producer e consumer **precisam**
suportar o formato.

## Estado de implementação

### ✅ Producer .NET

- `Apache.Avro` + `Confluent.SchemaRegistry.Serdes.Avro` no csproj
- `AvroSerdes.cs`: parseia o JSON do outbox, constrói `GenericRecord` field-by-field
  via `JObject` → `RecordSchema`, e usa `AvroSerializer<GenericRecord>` que injeta
  o header Confluent e serializa o body
- `OutboxRelayHostedService`: producer trocado pra `<string, byte[]>`. Pra topics
  configurados em `Outbox__AvroTopics`, chama `AvroSerdes.SerializeAsync`. Pros
  demais, continua UTF-8 JSON.
- Schema cache em memória: primeira mensagem por topic baixa do registry, resto é hit.

### ⏸ Consumer PyFlink — DESLIGADO por default

O `KafkaSource.builder().set_value_only_deserializer(SimpleStringSchema())`
hoje retorna `str`. Pra ler bytes Avro, o deserializer precisa retornar `bytes`.
Em PyFlink 1.18 isso exige:

1. Implementar uma `DeserializationSchema` Python que devolva `Types.PRIMITIVE_ARRAY(BYTE)`, **OU**
2. Usar `KafkaRecordDeserializationSchema` via Java gateway (JNI)

Ambas opções adicionam ~50 linhas e expõem o operator a `bytes` em vez de `str`,
quebrando muitos asserts existentes. Custo alto vs benefício zero da demo.

**Decisão**: ativação completa fica reservada pra Sprint 7. Hoje:
- Schema Registry conhece os schemas (Sprint 5.C)
- Producer .NET tem código Avro implementado e testado em build
- Default `Outbox__AvroTopics=""` mantém JSON no wire — consumer atual não muda
- Documentação inclui exemplo `Outbox__AvroTopics=transferencia.solicitada` pra
  quando o consumer suportar

## Plano Sprint 7 (ativação)

```python
# pyflink/fraud_detector_job.py
from pyflink.common.serialization import DeserializationSchema
import fastavro, io, requests

class BytesValueDeserializer(DeserializationSchema):
    def deserialize(self, message):
        return bytes(message)

# … no main, trocar:
.set_value_only_deserializer(BytesValueDeserializer())

# … no process_element:
def _decode_value(self, raw_bytes: bytes) -> dict:
    if len(raw_bytes) > 5 and raw_bytes[0] == 0x00:
        schema_id = int.from_bytes(raw_bytes[1:5], "big")
        # cache schema_id → fastavro_schema (busca uma vez no registry)
        schema = self._schema_by_id(schema_id)
        return fastavro.schemaless_reader(io.BytesIO(raw_bytes[5:]), schema)
    return json.loads(raw_bytes.decode("utf-8"))  # fallback JSON
```

`fastavro` + `requests` já vêm no Dockerfile.flink (Sprint 6.B).

## Consequências

- ✅ Producer .NET pronto pra Avro (toda a serialização funciona, com schema cache)
- ✅ Schema Registry continua sendo fonte de verdade (Sprint 5.C)
- ✅ Switch é por env var: `Outbox__AvroTopics=transferencia.solicitada`
- ✅ Wire format Confluent (5-byte header) — compatível com qualquer consumer
  oficial do ecossistema
- ⚠ Consumer Python ainda lê JSON — Avro só está "armado" no producer
- ⚠ Activate sem migrar consumer = mensagens órfãs (PyFlink falha em parsear).
  Por isso default é OFF.
