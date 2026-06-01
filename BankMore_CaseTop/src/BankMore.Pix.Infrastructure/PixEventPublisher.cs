using System.Text.Json;
using BankMore.Pix.Domain;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// Publica `pix.liquidada` no Kafka após cada liquidação. Esse evento alimenta a
/// análise pós-liquidação em streaming (Tarifas.Worker enriquece o feature store
/// no Redis + alerta de burst), sem bloquear o pagamento — a decisão de bloqueio
/// já foi feita inline (Sprint 9). Defesa em profundidade: scoring inline (rápido,
/// bloqueante) + análise em janela (pós-fato, enriquece o modelo p/ os próximos).
///
/// key = cpfOrigem → garante ordenação por pagador na partição (burst do mesmo CPF
/// chega ordenado no consumer).
///
/// Best-effort com acks=1 (não all): perder um evento de enriquecimento não é
/// crítico — o pagamento já liquidou e foi auditado no Postgres.
/// </summary>
public sealed class PixEventPublisher : IPixEventPublisher, IDisposable
{
    public const string TopicLiquidada = "pix.liquidada";

    private readonly IProducer<string, string> _producer;
    private readonly ILogger<PixEventPublisher> _log;

    public PixEventPublisher(string broker, ILogger<PixEventPublisher> log)
    {
        _log = log;
        var config = new ProducerConfig
        {
            BootstrapServers = broker,
            Acks = Acks.Leader,
            EnableIdempotence = false,
            MessageTimeoutMs = 3000,
            LingerMs = 5,
        };
        _producer = new ProducerBuilder<string, string>(config).Build();
    }

    public async Task PublicarLiquidada(PixPagamento p, CancellationToken ct)
    {
        try
        {
            var evt = new
            {
                id = p.Id,
                e2eId = p.E2eId,
                cpfOrigem = p.CpfOrigem,
                cpfDestino = p.CpfDestino,
                valor = p.Valor,
                tipoIniciacao = p.TipoIniciacao.ToString(),
                scoreFraude = p.ScoreFraude,
                timestamp = (p.LiquidadoEm ?? DateTimeOffset.UtcNow).ToUnixTimeMilliseconds(),
            };
            var json = JsonSerializer.Serialize(evt);
            await _producer.ProduceAsync(TopicLiquidada,
                new Message<string, string> { Key = p.CpfOrigem, Value = json }, ct);
        }
        catch (Exception ex)
        {
            // Best-effort: enriquecimento não pode derrubar o fluxo de pagamento
            _log.LogWarning(ex, "Falha publicando pix.liquidada e2e={E2e} (best-effort)", p.E2eId);
        }
    }

    public void Dispose()
    {
        _producer.Flush(TimeSpan.FromSeconds(3));
        _producer.Dispose();
    }
}
