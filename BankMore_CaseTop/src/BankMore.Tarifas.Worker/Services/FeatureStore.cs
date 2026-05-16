using StackExchange.Redis;
using Microsoft.Extensions.Logging;

namespace BankMore.Tarifas.Worker.Services;

/// <summary>
/// Feature store rolling em Redis. Populado pelo Worker quando uma transferência
/// é EFETIVADA; consultado pelo PyFlink no /predict.
///
/// Layout das chaves (por CPF origem):
///   feat:{cpf}:count_1h         INCR + EXPIRE 3600s — contador rolling de 1h
///   feat:{cpf}:valores_24h      LIST com push + LTRIM 100 + EXPIRE 86400s — últimos 100 valores
///   feat:{cpf}:valores_30d      ZSET com score=timestamp_ms — últimos 30 dias (limita 1000)
///
/// O PyFlink lê via HGET/LRANGE/ZRANGE no /predict. Latência típica < 2ms.
/// </summary>
public class FeatureStore
{
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<FeatureStore> _logger;

    public FeatureStore(IConnectionMultiplexer redis, ILogger<FeatureStore> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    /// <summary>
    /// Atualiza as features rolling após uma transferência ser efetivada.
    /// Idempotente (transferenciaId no Redis pra evitar dupla contagem se a mensagem replay).
    /// </summary>
    public async Task RegistrarTransferenciaEfetivada(
        string cpfOrigem, decimal valor, DateTime quando, string transferenciaId)
    {
        if (string.IsNullOrWhiteSpace(cpfOrigem)) return;

        try
        {
            var db = _redis.GetDatabase();
            var dedupKey = $"feat:dedup:{transferenciaId}";

            // Idempotência via SET NX EX (1h): se já tem a chave, não conta de novo
            var added = await db.StringSetAsync(dedupKey, "1", TimeSpan.FromHours(1), When.NotExists);
            if (!added)
            {
                _logger.LogDebug("FeatureStore: {Id} já registrada, pulando", transferenciaId);
                return;
            }

            var tsMs = new DateTimeOffset(quando).ToUnixTimeMilliseconds();
            var valorStr = ((double)valor).ToString(System.Globalization.CultureInfo.InvariantCulture);

            // Pipeline (todas as ops vão num único round-trip)
            var tasks = new List<Task>
            {
                // count_1h: INCR + EXPIRE 3600s (TTL renovado a cada incremento — janela rolling rouca,
                // mas dispensa ZSET por timestamp e é OK pra demo. Sprint futuro: ZSET preciso).
                db.StringIncrementAsync($"feat:{cpfOrigem}:count_1h"),
                db.KeyExpireAsync($"feat:{cpfOrigem}:count_1h", TimeSpan.FromHours(1)),

                // valores_24h: LPUSH + LTRIM(0,99) + EXPIRE — últimos 100 valores
                db.ListLeftPushAsync($"feat:{cpfOrigem}:valores_24h", valorStr),
                db.ListTrimAsync($"feat:{cpfOrigem}:valores_24h", 0, 99),
                db.KeyExpireAsync($"feat:{cpfOrigem}:valores_24h", TimeSpan.FromHours(24)),

                // valores_30d: ZSET por timestamp_ms, mantém últimos 1000
                db.SortedSetAddAsync($"feat:{cpfOrigem}:valores_30d", valorStr + ":" + tsMs, tsMs),
                db.SortedSetRemoveRangeByRankAsync($"feat:{cpfOrigem}:valores_30d", 0, -1001),
                db.KeyExpireAsync($"feat:{cpfOrigem}:valores_30d", TimeSpan.FromDays(30)),
            };

            await Task.WhenAll(tasks);
        }
        catch (Exception ex)
        {
            // Feature store é best-effort: falha aqui não pode quebrar a efetivação no Postgres.
            _logger.LogWarning(ex, "FeatureStore: erro registrando {Id} (best-effort, ignorado)", transferenciaId);
        }
    }
}
