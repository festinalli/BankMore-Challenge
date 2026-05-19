using BankMore.Transferencia.Domain;
using Confluent.Kafka;
using Prometheus;

namespace BankMore.Transferencia.Api.Services;

/// <summary>
/// Sprint 5.B — OutboxRelay: lê transferencia_outbox em loop e publica no Kafka.
///
/// Por que rodar como HostedService dentro da Transferencia.Api (em vez de
/// .NET Worker separado):
///   - mesmo banco/connection pool já configurado
///   - 1 réplica é suficiente (single-leader simples; FOR UPDATE SKIP LOCKED
///     permite escalar pra N réplicas sem race)
///   - se a API cair, ninguém publica — mas a API é o ÚNICO produtor mesmo
///
/// Estratégia:
///   - Poll a cada POLL_INTERVAL_MS (default 500ms)
///   - Lote de até BATCH_SIZE rows com FOR UPDATE SKIP LOCKED
///   - Para cada row: produce com `acks=all`, `enable.idempotence=true`
///   - Sucesso → MarcarPublicado. Falha → MarcarFalha (incrementa tentativas,
///     próximo poll só pega após backoff exponencial)
///   - Sem DLQ ainda — depois de N tentativas vai virar TODO Sprint 6
/// </summary>
public class OutboxRelayHostedService(
    IServiceProvider services,
    IConfiguration cfg,
    ILogger<OutboxRelayHostedService> logger
) : BackgroundService
{
    private static readonly Counter _publicados = Metrics.CreateCounter(
        "bankmore_outbox_publicados_total",
        "Total de mensagens do outbox publicadas no Kafka, por topic.",
        new CounterConfiguration { LabelNames = new[] { "topic" } });

    private static readonly Counter _falhas = Metrics.CreateCounter(
        "bankmore_outbox_falhas_total",
        "Total de falhas ao publicar do outbox, por motivo.",
        new CounterConfiguration { LabelNames = new[] { "motivo" } });

    private static readonly Histogram _lote = Metrics.CreateHistogram(
        "bankmore_outbox_lote_size",
        "Tamanho do lote lido por iteração.",
        new HistogramConfiguration { Buckets = new double[] { 0, 1, 5, 10, 25, 50, 100 } });

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var pollMs = cfg.GetValue<int?>("Outbox:PollIntervalMs") ?? 500;
        var batch  = cfg.GetValue<int?>("Outbox:BatchSize") ?? 50;
        var broker = cfg["Kafka:Broker"] ?? throw new InvalidOperationException("Kafka:Broker ausente");

        var producerConfig = new ProducerConfig
        {
            BootstrapServers = broker,
            Acks = Acks.All,                     // forte garantia
            EnableIdempotence = true,            // sem duplicatas em retry do producer
            MessageSendMaxRetries = 5,
            LingerMs = 5,
            CompressionType = CompressionType.Lz4,
            ClientId = "outbox-relay-transferencia",
        };

        using var producer = new ProducerBuilder<string, string>(producerConfig).Build();

        logger.LogInformation("OutboxRelay iniciado: poll={Poll}ms batch={Batch} broker={Broker}",
            pollMs, batch, broker);

        // Conexão de serviço por iteração — repository é singleton, abre/fecha conexão
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var scope = services.CreateScope();
                var repo = scope.ServiceProvider.GetRequiredService<ITransferenciaRepository>();

                var pendentes = await repo.LerPendentes(batch, stoppingToken);
                _lote.Observe(pendentes.Count);

                if (pendentes.Count == 0)
                {
                    await Task.Delay(pollMs, stoppingToken);
                    continue;
                }

                foreach (var item in pendentes)
                {
                    try
                    {
                        // Key = transferenciaId pra particionar consistente no Kafka
                        var dr = await producer.ProduceAsync(
                            item.Topic,
                            new Message<string, string>
                            {
                                Key = item.TransferenciaId,
                                Value = item.PayloadJson,
                            },
                            stoppingToken);

                        await repo.MarcarPublicado(item.Id, stoppingToken);
                        _publicados.WithLabels(item.Topic).Inc();

                        logger.LogDebug("Outbox publicada {Id} → {Topic}/{Partition}@{Offset}",
                            item.Id, item.Topic, dr.Partition.Value, dr.Offset.Value);
                    }
                    catch (ProduceException<string, string> ex)
                    {
                        _falhas.WithLabels("kafka_produce").Inc();
                        logger.LogWarning("Falha ao publicar outbox {Id} tentativa={N}: {Err}",
                            item.Id, item.Tentativas + 1, ex.Error.Reason);
                        await repo.MarcarFalha(item.Id, ex.Error.Reason, stoppingToken);
                    }
                    catch (Exception ex)
                    {
                        _falhas.WithLabels(ex.GetType().Name).Inc();
                        logger.LogError(ex, "Erro inesperado publicando outbox {Id}", item.Id);
                        await repo.MarcarFalha(item.Id, ex.Message, stoppingToken);
                    }
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _falhas.WithLabels("loop").Inc();
                logger.LogError(ex, "OutboxRelay: erro no loop, dormindo 5s");
                await Task.Delay(5000, stoppingToken);
            }
        }

        logger.LogInformation("OutboxRelay encerrado");
    }
}
