using BankMore.Transferencia.Domain;
using Confluent.Kafka;
using Confluent.SchemaRegistry;
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

    private static readonly Counter _dlq = Metrics.CreateCounter(
        "bankmore_outbox_dlq_total",
        "Mensagens movidas para DLQ (Sprint 6.A), por motivo.",
        new CounterConfiguration { LabelNames = new[] { "motivo" } });

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var pollMs    = cfg.GetValue<int?>("Outbox:PollIntervalMs")    ?? 500;
        var batch     = cfg.GetValue<int?>("Outbox:BatchSize")         ?? 50;
        // Sprint 6.A: após N tentativas, move pra DLQ.
        var maxTries  = cfg.GetValue<int?>("Outbox:MaxTentativas")     ?? 5;
        var broker = cfg["Kafka:Broker"] ?? throw new InvalidOperationException("Kafka:Broker ausente");

        // Sprint 6.B — controle de quais topics vão em Avro binário.
        // Padrão: só transferencia.solicitada (canal de entrada do pipeline).
        // Os outros (não publicados por este relay hoje) continuariam JSON quando
        // forem migrados.
        var avroTopicsCsv = cfg["Outbox:AvroTopics"] ?? "transferencia.solicitada";
        var avroTopics = new HashSet<string>(avroTopicsCsv.Split(',', StringSplitOptions.RemoveEmptyEntries
                                                                | StringSplitOptions.TrimEntries));

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

        // Producer<string, byte[]>: Key=transferencia_id (UTF8), Value=bytes.
        // - Topics Avro: serializer .NET injeta magic byte + schema_id + Avro body
        // - Topics JSON: bytes = UTF8 do JSON original do outbox
        using var producer = new ProducerBuilder<string, byte[]>(producerConfig).Build();

        // Sprint 6.B — AvroSerdes resolvido via DI.
        AvroSerdes? avroSerdes = null;
        try
        {
            using var scope0 = services.CreateScope();
            avroSerdes = scope0.ServiceProvider.GetService<AvroSerdes>();
        }
        catch { /* sem schema registry → todos topics serão tratados como JSON */ }

        logger.LogInformation(
            "OutboxRelay iniciado: poll={Poll}ms batch={Batch} maxTries={MaxTries} broker={Broker} avro_topics={AvroTopics}",
            pollMs, batch, maxTries, broker, string.Join(',', avroTopics));

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
                        // Sprint 6.B — serializa Avro binário pra topics configurados,
                        // JSON UTF-8 pros demais. Magic byte 0x00 + schema_id é injetado
                        // pelo AvroSerializer (formato wire do Confluent).
                        byte[] valueBytes;
                        if (avroSerdes != null && avroTopics.Contains(item.Topic))
                        {
                            valueBytes = await avroSerdes.SerializeAsync(
                                item.Topic, item.PayloadJson, stoppingToken);
                        }
                        else
                        {
                            valueBytes = System.Text.Encoding.UTF8.GetBytes(item.PayloadJson);
                        }

                        // Key = transferenciaId pra particionar consistente no Kafka
                        var dr = await producer.ProduceAsync(
                            item.Topic,
                            new Message<string, byte[]>
                            {
                                Key = item.TransferenciaId,
                                Value = valueBytes,
                            },
                            stoppingToken);

                        await repo.MarcarPublicado(item.Id, stoppingToken);
                        _publicados.WithLabels(item.Topic).Inc();

                        logger.LogDebug("Outbox publicada {Id} → {Topic}/{Partition}@{Offset} ({Bytes} bytes)",
                            item.Id, item.Topic, dr.Partition.Value, dr.Offset.Value, valueBytes.Length);
                    }
                    catch (ProduceException<string, byte[]> ex)
                    {
                        await HandleFalha(repo, item, "kafka_produce", ex.Error.Reason, maxTries, stoppingToken);
                    }
                    catch (Exception ex)
                    {
                        await HandleFalha(repo, item, ex.GetType().Name, ex.Message, maxTries, stoppingToken);
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

    /// <summary>
    /// Sprint 6.A — política de retry/DLQ: tentativas++ até maxTries; depois move pra DLQ.
    /// Métricas separadas: falha normal incrementa _falhas; DLQ incrementa _dlq.
    /// </summary>
    private async Task HandleFalha(
        BankMore.Transferencia.Domain.ITransferenciaRepository repo,
        BankMore.Transferencia.Domain.OutboxItem item,
        string motivoCounter,
        string mensagemErro,
        int maxTries,
        CancellationToken ct)
    {
        var proximaTentativa = item.Tentativas + 1;
        _falhas.WithLabels(motivoCounter).Inc();

        if (proximaTentativa >= maxTries)
        {
            logger.LogError(
                "Outbox {Id} EXCEDEU {Max} tentativas — movendo pra DLQ. Último erro: {Err}",
                item.Id, maxTries, mensagemErro);
            await repo.MoverParaDeadLetter(item.Id, mensagemErro, ct);
            _dlq.WithLabels(motivoCounter).Inc();
        }
        else
        {
            logger.LogWarning(
                "Falha ao publicar outbox {Id} tentativa={N}/{Max}: {Err}",
                item.Id, proximaTentativa, maxTries, mensagemErro);
            await repo.MarcarFalha(item.Id, mensagemErro, ct);
        }
    }
}
