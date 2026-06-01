using BankMore.Pix.Application;
using BankMore.Pix.Domain;
using MediatR;
using Prometheus;

namespace BankMore.Pix.Api.Services;

/// <summary>
/// Sprint 8.E — scheduler do PIX Automático.
///
/// Varre consentimentos AUTORIZADOS cuja proxima_cobranca já venceu e dispara a
/// cobrança recorrente. O handler reagenda a próxima conforme a periodicidade.
///
/// Em produção isso seria um job distribuído (Quartz/Hangfire) com lock pra evitar
/// dupla cobrança em múltiplas réplicas. Aqui, single-replica + poll simples, com
/// SELECT ... vencidos sendo idempotente o suficiente pra demo.
/// </summary>
public sealed class RecorrenciaScheduler(
    IServiceProvider services,
    IConfiguration cfg,
    ILogger<RecorrenciaScheduler> logger
) : BackgroundService
{
    private static readonly Counter _cobrancas = Metrics.CreateCounter(
        "bankmore_pix_automatico_cobrancas_total", "Cobranças recorrentes disparadas", "status");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var intervalSec = int.Parse(cfg["PixAutomatico:PollIntervalSeconds"] ?? "30");
        var interval = TimeSpan.FromSeconds(Math.Clamp(intervalSec, 5, 3600));
        logger.LogInformation("RecorrenciaScheduler iniciado: poll={Sec}s", intervalSec);

        // Atraso inicial pra não competir com boot
        try { await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken); }
        catch (OperationCanceledException) { return; }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var scope = services.CreateScope();
                var repo = scope.ServiceProvider.GetRequiredService<IPixRepository>();
                var mediator = scope.ServiceProvider.GetRequiredService<IMediator>();

                var vencidos = await repo.ListarConsentimentosVencidos(DateTimeOffset.UtcNow, stoppingToken);
                foreach (var c in vencidos)
                {
                    var r = await mediator.Send(new ExecutarCobrancaConsentimentoCommand(c.Id), stoppingToken);
                    _cobrancas.WithLabels(r.Status).Inc();
                    logger.LogInformation("PIX Automático cobrança consent={Id} status={St} valor={V}",
                        c.Id, r.Status, r.Valor);
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                logger.LogError(ex, "Erro no scheduler de recorrência — retry no próximo ciclo");
            }

            try { await Task.Delay(interval, stoppingToken); }
            catch (OperationCanceledException) { break; }
        }
    }
}
