# 0016 — Sprint 7: Avro end-to-end + auth admin + retenção DLQ

**Status:** Aceito · **Data:** 2026-05-19

## Contexto

Sprint 6 deixou três débitos técnicos rastreados:

1. **Avro só no producer** (ADR 0015): consumer PyFlink ainda lia String/JSON;
   producer .NET serializava Avro mas o switch ficava sempre desligado pra
   não derrubar o consumer.
2. **Endpoints admin do outbox sem auth** (ADR 0014): `/api/admin/outbox/*`
   aceitava qualquer request — "aceitável só pela rede interna do compose",
   mas pegar um repositório de portfolio com endpoint admin aberto fica feio.
3. **DLQ sem retenção** (ADR 0014): rows em DLQ permaneciam indefinidamente.

Sprint 7 fecha os três.

## Decisão

### 7.A — Avro end-to-end (truque do Latin-1)

PyFlink 1.18 só oferece dois caminhos pra ler bytes do Kafka:

- `KafkaRecordDeserializationSchema` Java via JNI (~50 linhas + gateway PyFlink/Java)
- Implementar `DeserializationSchema` Python custom que retorne `Types.PRIMITIVE_ARRAY(BYTE)`

Ambos eram o plano original do ADR 0015. Em vez disso, descobri um terceiro
caminho **muito mais simples**: `SimpleStringSchema('ISO-8859-1')`.

Por que funciona:
- Latin-1 (ISO-8859-1) mapeia bytes 0-255 → codepoints Unicode 0-255 **bijetivamente**
- `SimpleStringSchema('ISO-8859-1')` decoda qualquer sequência de bytes Kafka
  em uma string Python sem corromper nada
- No operator Python, `value.encode('latin-1')` recupera os bytes originais
- Daí: detect magic byte (`0x00`), parse schema_id (bytes 1-5 BE), decode com
  `fastavro.schemaless_reader`

Trade-off: passamos por uma string Python intermediária (mais uma alocação que
o caminho direto-bytes). Pra um payload Avro de ~150 bytes a 1k msg/s isso é
ruído. Em troca: **zero JNI, zero `DeserializationSchema` custom, zero quebra
de testes existentes** (interface do operator continua `str`).

Schema cache: `dict[int, dict]` em variável de módulo. Sem locks (GIL +
writes idempotentes). Cada Python worker do PyFlink baixa cada schema_id no
máximo 1× do registry.

Fallback JSON mantido: se `bytes[0] != 0x00`, tenta `json.loads`. Garante
compatibilidade com mensagens antigas do tópico (não preciso esvaziar Kafka)
e permite reverter o switch (`Outbox__AvroTopics=""`) sem rebuild do
detector.

### 7.B — Auth shared-secret nos endpoints admin

Criei `[RequireAdminToken]` action filter:
- Lê `Outbox__AdminToken` do `IConfiguration`
- Espera `Authorization: Bearer <token>` no request
- Comparação constant-time (`FixedTimeEquals`) — overkill pra demo, mas
  escrever certo desde o início ajuda quem for ler o código
- **Fail-closed**: se `Outbox__AdminToken` não estiver configurado, retorna
  503. Evita o footgun de subir em prod sem env e expor admin pra todos.

Por que não JWT: o JWT do BankMore é emitido pelo `ContaCorrente.Api` com
claim `sub=cpf` (cliente final). Reaproveitar exigiria endpoint de admin
login + tabela de operadores + role mapping. Pra v1 de demo, shared-secret
em env var é proporcional ao risco. Sprint 8+ troca por JWT com `role=ops`
emitido por IdP separado.

### 7.C — Retenção automática de DLQ

`DlqRetentionHostedService` (BackgroundService) roda `DELETE FROM
transferencia_outbox WHERE dead_letter_em < NOW() - INTERVAL 'N days'`:

- `Outbox__DlqRetentionDays`: 30 (default)
- `Outbox__DlqRetentionIntervalHours`: 24 (1×/dia)
- Atraso inicial de 2 min pra não competir com boot
- Idempotente: pode rodar em N réplicas sem coordenação
- Métrica: `bankmore_outbox_dlq_expiradas_total` (Counter)

INTERVAL com placeholder não funciona direto em Npgsql; uso composição
string + `Math.Clamp(dias, 1, 3650)`. Input vem de config interna, não de
usuário — sem risco de injection.

## Consequências

- ✅ **Avro fechado fim-a-fim**: producer .NET → wire format Confluent (5-byte
  header) → consumer PyFlink decoda via fastavro. Schema Registry como fonte
  de verdade.
- ✅ **Switch reversível por env**: `Outbox__AvroTopics=""` volta pra JSON
  imediatamente (sem rebuild). Útil pra incident response.
- ✅ **Endpoints admin protegidos** (validado 401/401/200 nos 3 caminhos:
  sem token, token errado, token correto).
- ✅ **DLQ não cresce indefinidamente** — retention configurável via env.
- ⚠ **Performance Avro**: cada msg passa por `bytes → str (latin-1) → bytes`.
  Custo desprezível pro volume da demo. Se quiser otimizar, Sprint 9 pode
  implementar `KafkaRecordDeserializationSchema` Java custom.
- ⚠ **Auth admin com shared-secret**: simples mas inferior a JWT+role.
  Sprint 8 deve migrar.
- ⚠ **e2e cenário 3 falha (preexistente, não-Sprint-7)**: ML rejeita TED
  R$ 12k Bob→Alice quando rodado de noite no Brasil porque `hora_do_dia`
  é computado em UTC (22h Brasília = 01h UTC → modelo aprendeu como
  horário de fraude). Bug preexistente do training data, sem relação com
  Sprint 7. Spawnei task separada pra arrumar.

## Validação manual

```bash
# Auth admin
curl -i http://localhost:5001/api/admin/outbox/dlq                                       # 401
curl -i -H "Authorization: Bearer wrong" http://localhost:5001/api/admin/outbox/dlq      # 401
curl -i -H "Authorization: Bearer dev-admin-not-for-prod" http://localhost:5001/api/admin/outbox/dlq  # 200

# Avro no wire (partition 0/2):
docker exec bankmore-kafka kafka-console-consumer --bootstrap-server localhost:9092 \
    --topic transferencia.solicitada --partition 0 --offset latest --max-messages 1 | xxd | head -3
# 00 00 00 00 01 48 ... (magic=0x00 schema_id=1 payload Avro)

# Retenção DLQ (manual trigger via debug):
docker logs bankmore-transferencia-api | grep DlqRetention
# DlqRetention iniciado: retencao=30d intervalo=24h
```
