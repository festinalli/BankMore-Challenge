using BankMore.Transferencia.Domain;
using Prometheus;

namespace BankMore.Transferencia.Api.Services;

/// <summary>
/// Sprint 7.C — apaga rows de DLQ mais antigas que <c>Outbox__DlqRetentionDays</c> (default 30).
///
/// Por que background dentro da API (mesmo padrão do OutboxRelay):
///   - Mesmo connection pool, evita serviço novo
///   - Idempotente: pode rodar em N réplicas (DELETE só remove o que estiver fora da janela)
///   - Frequência baixa (1×/dia) → custo desprezível
///
/// Sem retenção a tabela cresce indefinidamente. Sprint 6.A já alertava isso na ADR 0014.
/// </summary>
public class DlqRetentionHostedService(
    IServiceProvider services,
    IConfiguration cfg,
    ILogger<DlqRetentionHostedService> logger
) : BackgroundService
{
    private static readonly Counter _removidas = Metrics.CreateCounter(
        "bankmore_outbox_dlq_expiradas_total",
        "Total de rows DLQ removidas pela retencao automatica (Sprint 7.C)");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var retentionDays = int.Parse(cfg["Outbox:DlqRetentionDays"] ?? "30");
        var intervalHours = int.Parse(cfg["Outbox:DlqRetentionIntervalHours"] ?? "24");
        var interval = TimeSpan.FromHours(Math.Clamp(intervalHours, 1, 168));

        logger.LogInformation("DlqRetention iniciado: retencao={Days}d intervalo={Hours}h",
            retentionDays, intervalHours);

        // Atraso inicial pra não competir com boot da API + outras inicializações.
        try { await Task.Delay(TimeSpan.FromMinutes(2), stoppingToken); }
        catch (OperationCanceledException) { return; }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var scope = services.CreateScope();
                var repo = scope.ServiceProvider.GetRequiredService<ITransferenciaRepository>();
                var removed = await repo.ExpirarDeadLetter(retentionDays, stoppingToken);

                if (removed > 0)
                {
                    _removidas.Inc(removed);
                    logger.LogInformation("DLQ retention: {Count} rows removidas (> {Days} dias)",
                        removed, retentionDays);
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                // Falha aqui não é crítica — só tentamos de novo no próximo ciclo.
                logger.LogError(ex, "Erro na retencao DLQ — vai tentar de novo em {Hours}h", intervalHours);
            }

            try { await Task.Delay(interval, stoppingToken); }
            catch (OperationCanceledException) { break; }
        }
    }
}
