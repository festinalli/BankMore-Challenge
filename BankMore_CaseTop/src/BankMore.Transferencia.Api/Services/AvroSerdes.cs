using Avro.Generic;
using Confluent.Kafka;
using Confluent.SchemaRegistry;
using Confluent.SchemaRegistry.Serdes;
using Newtonsoft.Json.Linq;
using Schema = Avro.Schema;
using RecordSchema = Avro.RecordSchema;
using EnumSchema = Avro.EnumSchema;
using ArraySchema = Avro.ArraySchema;

namespace BankMore.Transferencia.Api.Services;

/// <summary>
/// Sprint 6.B — serializa JSON do outbox em Avro binário (formato Confluent wire:
/// magic byte 0x00 + schema_id big-endian + bytes Avro).
///
/// Estratégia:
///   - Schema é resolvido por topic via TopicNameStrategy: <topic>-value
///   - GenericRecord construído field-by-field a partir do JObject (parsed do
///     JSONB do outbox) — sem precisar de codegen avrogen na pipeline.
///   - Cache de Schema parsed em memória (Map<topic, RecordSchema>) — primeira
///     mensagem por topic faz HTTP no Schema Registry; resto é cache hit.
///
/// Limitações conhecidas:
///   - Suporta tipos primitivos, enum, string, long, int, double, boolean.
///   - Sem union nullable arbitrário (precisaria escolher tipo via schema).
///     O schema TransferenciaSolicitada não tem nullable, então OK.
///   - Defaults do schema NÃO são aplicados — caller precisa garantir presença
///     dos campos ou ajustar JSON antes.
/// </summary>
public class AvroSerdes
{
    private readonly ISchemaRegistryClient _registry;
    private readonly Dictionary<string, RecordSchema> _schemaCache = new();
    private readonly SemaphoreSlim _cacheLock = new(1, 1);
    private readonly ILogger<AvroSerdes> _logger;
    private readonly AvroSerializer<GenericRecord> _serializer;

    public AvroSerdes(ISchemaRegistryClient registry, ILogger<AvroSerdes> logger)
    {
        _registry = registry;
        _logger = logger;
        _serializer = new AvroSerializer<GenericRecord>(_registry, new AvroSerializerConfig
        {
            // SubjectNameStrategy default = TopicName: <topic>-value
            BufferBytes = 100,
        });
    }

    /// <summary>
    /// Serializa o payloadJson em Avro binário Confluent. Retorna bytes prontos
    /// pra Message.Value.
    /// </summary>
    public async Task<byte[]> SerializeAsync(string topic, string payloadJson, CancellationToken ct)
    {
        var schema = await GetOrLoadSchemaAsync($"{topic}-value", ct);
        var json = JObject.Parse(payloadJson);
        var record = JsonToGenericRecord(json, schema);

        var ctx = new SerializationContext(MessageComponentType.Value, topic);
        return await _serializer.SerializeAsync(record, ctx);
    }

    private async Task<RecordSchema> GetOrLoadSchemaAsync(string subject, CancellationToken ct)
    {
        if (_schemaCache.TryGetValue(subject, out var cached)) return cached;

        await _cacheLock.WaitAsync(ct);
        try
        {
            if (_schemaCache.TryGetValue(subject, out cached)) return cached;

            var registered = await _registry.GetLatestSchemaAsync(subject);
            var parsed = (RecordSchema)Schema.Parse(registered.SchemaString);
            _schemaCache[subject] = parsed;
            _logger.LogInformation("AvroSerdes: schema {Subject} carregado (id={Id})", subject, registered.Id);
            return parsed;
        }
        finally
        {
            _cacheLock.Release();
        }
    }

    /// <summary>
    /// Constrói GenericRecord a partir de JObject + RecordSchema. Recursivo pra records
    /// aninhados (não usado no schema atual mas previsto).
    /// </summary>
    private static GenericRecord JsonToGenericRecord(JObject json, RecordSchema schema)
    {
        var rec = new GenericRecord(schema);
        foreach (var field in schema.Fields)
        {
            var token = json[field.Name];
            if (token == null || token.Type == JTokenType.Null)
            {
                // se o schema não tem default, a validação do Avro lib vai falhar — OK
                continue;
            }
            rec.Add(field.Name, ConvertToken(token, field.Schema));
        }
        return rec;
    }

    private static object? ConvertToken(JToken token, Schema schema)
    {
        return schema.Tag switch
        {
            Schema.Type.String   => (string)token!,
            Schema.Type.Int      => (int)token,
            Schema.Type.Long     => (long)token,
            Schema.Type.Float    => (float)token,
            Schema.Type.Double   => (double)token,
            Schema.Type.Boolean  => (bool)token,
            Schema.Type.Enumeration => new GenericEnum((EnumSchema)schema, (string)token!),
            Schema.Type.Array    => ConvertArray(token, (ArraySchema)schema),
            Schema.Type.Record   => JsonToGenericRecord((JObject)token, (RecordSchema)schema),
            Schema.Type.Bytes    => Convert.FromBase64String((string)token!),
            _ => throw new NotSupportedException($"Tipo Avro não suportado: {schema.Tag}")
        };
    }

    private static IList<object?> ConvertArray(JToken token, ArraySchema schema)
    {
        var array = (JArray)token;
        var list = new List<object?>(array.Count);
        foreach (var item in array)
            list.Add(ConvertToken(item, schema.ItemSchema));
        return list;
    }
}
