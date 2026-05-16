using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using Confluent.Kafka;
using Microsoft.AspNetCore.Mvc;

namespace BankMore.ContaCorrente.Api.Controllers;

[ApiController]
[Route("api/admin/fraude")]
public class FraudeOpsController : ControllerBase
{
    private readonly IConfiguration _config;
    private readonly ILogger<FraudeOpsController> _logger;

    public FraudeOpsController(IConfiguration config, ILogger<FraudeOpsController> logger)
    {
        _config = config;
        _logger = logger;
    }

    // SSE: cada conexão abre 2 consumers efêmeros (group ID novo a cada GET) que escutam
    // fraude.alerta + transferencia.rejeitada a partir do offset corrente. Não persiste
    // estado entre conexões — recarregar a página perde o histórico, o que é coerente
    // com "painel ops em tempo real" da v1. Sprint 5 trocaria isso por um stream com
    // janela de 10min mantida em memória + auth role=ops.
    [HttpGet("stream")]
    public async Task Stream(CancellationToken clientCt)
    {
        var broker = _config["Kafka:Broker"]
            ?? Environment.GetEnvironmentVariable("Kafka__Broker")
            ?? "localhost:9092";

        Response.Headers["Content-Type"] = "text/event-stream";
        Response.Headers["Cache-Control"] = "no-cache";
        Response.Headers["X-Accel-Buffering"] = "no";

        var groupSuffix = Guid.NewGuid().ToString("N")[..8];
        var consumerConfig = new ConsumerConfig
        {
            BootstrapServers = broker,
            AutoOffsetReset = AutoOffsetReset.Latest,
            EnableAutoCommit = false,
            SessionTimeoutMs = 10000
        };

        var channel = Channel.CreateBounded<string>(new BoundedChannelOptions(256)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true
        });

        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(clientCt, HttpContext.RequestAborted);
        var ct = lifetime.Token;

        var alertaTask = Task.Run(() => PollTopic(
            broker, "fraude.alerta", $"fraud-ops-alerta-{groupSuffix}",
            "ALERTA", channel.Writer, ct), ct);

        var rejeitadaTask = Task.Run(() => PollTopic(
            broker, "transferencia.rejeitada", $"fraud-ops-rejeitada-{groupSuffix}",
            "REJEITADA", channel.Writer, ct), ct);

        try
        {
            await Response.Body.WriteAsync(Encoding.UTF8.GetBytes(": connected\n\n"), ct);
            await Response.Body.FlushAsync(ct);

            var heartbeat = Task.Run(async () =>
            {
                while (!ct.IsCancellationRequested)
                {
                    try
                    {
                        await Task.Delay(TimeSpan.FromSeconds(15), ct);
                        await channel.Writer.WriteAsync(":heartbeat", ct);
                    }
                    catch (OperationCanceledException) { return; }
                }
            }, ct);

            await foreach (var payload in channel.Reader.ReadAllAsync(ct))
            {
                var frame = payload.StartsWith(':')
                    ? payload + "\n\n"
                    : $"data: {payload}\n\n";
                await Response.Body.WriteAsync(Encoding.UTF8.GetBytes(frame), ct);
                await Response.Body.FlushAsync(ct);
            }
        }
        catch (OperationCanceledException) { /* cliente desconectou */ }
        finally
        {
            lifetime.Cancel();
            channel.Writer.TryComplete();
            try { await Task.WhenAll(alertaTask, rejeitadaTask); } catch { /* já cancelado */ }
        }
    }

    private void PollTopic(string broker, string topic, string groupId, string evento,
        ChannelWriter<string> writer, CancellationToken ct)
    {
        var cfg = new ConsumerConfig
        {
            BootstrapServers = broker,
            GroupId = groupId,
            AutoOffsetReset = AutoOffsetReset.Latest,
            EnableAutoCommit = false,
            SessionTimeoutMs = 10000,
            AllowAutoCreateTopics = false
        };

        using var consumer = new ConsumerBuilder<Ignore, string>(cfg).Build();
        consumer.Subscribe(topic);

        try
        {
            while (!ct.IsCancellationRequested)
            {
                ConsumeResult<Ignore, string>? result;
                try { result = consumer.Consume(TimeSpan.FromMilliseconds(500)); }
                catch (ConsumeException ex)
                {
                    _logger.LogWarning(ex, "Erro consumindo {Topic}", topic);
                    continue;
                }
                if (result?.Message?.Value is null) continue;

                var enriched = BuildEnvelope(evento, topic, result.Message.Value);
                if (!writer.TryWrite(enriched))
                {
                    // canal lotado — DropOldest já cuida; nada a fazer
                }
            }
        }
        catch (OperationCanceledException) { /* normal */ }
        finally
        {
            try { consumer.Close(); } catch { /* best effort */ }
        }
    }

    private static string BuildEnvelope(string evento, string topic, string raw)
    {
        // Tenta parsear o payload original e adicionar "evento" + "topico" sem
        // perder os campos do detector (id, cpfOrigem, valor, motivos, score, ...).
        try
        {
            using var doc = JsonDocument.Parse(raw);
            using var stream = new MemoryStream();
            using (var w = new Utf8JsonWriter(stream))
            {
                w.WriteStartObject();
                w.WriteString("evento", evento);
                w.WriteString("topico", topic);
                w.WriteString("recebidoEm", DateTime.UtcNow.ToString("O"));
                foreach (var prop in doc.RootElement.EnumerateObject())
                    prop.WriteTo(w);
                w.WriteEndObject();
            }
            return Encoding.UTF8.GetString(stream.ToArray());
        }
        catch
        {
            return JsonSerializer.Serialize(new { evento, topico = topic, raw });
        }
    }
}
