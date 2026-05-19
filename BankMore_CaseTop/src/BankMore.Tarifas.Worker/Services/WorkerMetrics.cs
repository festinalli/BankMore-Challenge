using Prometheus;

namespace BankMore.Tarifas.Worker.Services;

/// <summary>
/// Métricas de negócio do Worker. Expostas em /metrics (porta 9102) e
/// scrapeadas pelo Prometheus a cada 15s.
///
/// Por que estáticas: counters/histograms do prometheus-net são singletons
/// por nome — registrar via DI duplicaria. Pattern oficial da lib.
/// </summary>
public static class WorkerMetrics
{
    public static readonly Counter TransferenciaTotal = Metrics.CreateCounter(
        "bankmore_worker_transferencia_total",
        "Total de transferências processadas pelo Worker, particionado por status e tipo.",
        new CounterConfiguration { LabelNames = new[] { "status", "tipo" } });

    public static readonly Histogram EfetivacaoDuracao = Metrics.CreateHistogram(
        "bankmore_worker_efetivacao_duracao_seconds",
        "Duração da efetivação (transação Postgres + atualização Redis) em segundos.",
        new HistogramConfiguration
        {
            Buckets = new[] { 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0 }
        });

    public static readonly Counter TarifaCobradaBrl = Metrics.CreateCounter(
        "bankmore_worker_tarifa_cobrada_brl_total",
        "Total de tarifa cobrada (em BRL) particionado por tipo de transferência.",
        new CounterConfiguration { LabelNames = new[] { "tipo" } });

    public static readonly Counter CompensacaoTotal = Metrics.CreateCounter(
        "bankmore_worker_compensacao_total",
        "Transferências compensadas (rejeitadas após chegada no Worker), por motivo.",
        new CounterConfiguration { LabelNames = new[] { "motivo" } });
}
