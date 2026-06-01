using BankMore.Tarifas.Worker.Services;
using KafkaFlow;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Prometheus;

namespace BankMore.Tarifas.Worker.Handlers;

/// <summary>
/// Sprint 10.A — análise pós-liquidação do PIX (streaming).
///
/// Consome `pix.liquidada` e:
///   1. Enriquece o feature store no Redis (mesmo das transferências) — o histórico
///      PIX passa a influenciar o scoring de fraude de TODOS os canais.
///   2. Detecta burst pós-fato: se o count_1h do CPF cruzar o limiar, emite alerta
///      (métrica + log). Não bloqueia — o pagamento já liquidou; é defesa em
///      profundidade que alimenta investigação e o scoring dos PRÓXIMOS pagamentos.
///
/// Diferença pro scoring inline (Sprint 9): aquele decide ANTES de liquidar (bloqueia);
/// este observa DEPOIS (monitora + enriquece). Juntos: rápido na borda, profundo na janela.
/// </summary>
public class PixLiquidadoConsumer(
    IConfiguration configuration,
    ILogger<PixLiquidadoConsumer> logger,
    FeatureStore featureStore)
    : IMessageHandler<PixLiquidadaMessage>
{
    private static readonly Counter _processados = Metrics.CreateCounter(
        "bankmore_pix_pos_liquidacao_total", "Eventos pix.liquidada processados", "tipo_iniciacao");
    private static readonly Counter _alertasBurst = Metrics.CreateCounter(
        "bankmore_pix_alerta_burst_total", "Alertas de burst pós-liquidação no PIX");

    private readonly int _limiarBurst = int.Parse(
        configuration["Pix:LimiarBurstAlerta"]
        ?? Environment.GetEnvironmentVariable("PIX_LIMIAR_BURST_ALERTA") ?? "8");

    public async Task Handle(IMessageContext context, PixLiquidadaMessage message)
    {
        if (string.IsNullOrWhiteSpace(message.CpfOrigem)) return;

        var quando = DateTimeOffset.FromUnixTimeMilliseconds(
            message.Timestamp > 0 ? message.Timestamp : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).UtcDateTime;

        var count = await featureStore.RegistrarPixLiquidado(
            message.CpfOrigem, message.Valor, quando, message.Id);

        _processados.WithLabels(message.TipoIniciacao ?? "DESCONHECIDO").Inc();

        if (count >= _limiarBurst)
        {
            _alertasBurst.Inc();
            logger.LogWarning(
                "ALERTA burst PIX pós-liquidação: cpf={Cpf} count_1h={Count} (limiar={Limiar}) e2e={E2e}",
                Mask(message.CpfOrigem), count, _limiarBurst, message.E2eId);
        }
        else
        {
            logger.LogInformation("pix.liquidada processada cpf={Cpf} valor={Valor} count_1h={Count}",
                Mask(message.CpfOrigem), message.Valor, count);
        }
    }

    private static string Mask(string cpf) =>
        string.IsNullOrEmpty(cpf) || cpf.Length < 4 ? "***" : cpf[..3] + "***";
}

/// <summary>Evento emitido pelo pix-api em `pix.liquidada`.</summary>
public class PixLiquidadaMessage
{
    public string Id { get; set; } = string.Empty;
    public string E2eId { get; set; } = string.Empty;
    public string CpfOrigem { get; set; } = string.Empty;
    public string CpfDestino { get; set; } = string.Empty;
    public decimal Valor { get; set; }
    public string? TipoIniciacao { get; set; }
    public decimal? ScoreFraude { get; set; }
    public long Timestamp { get; set; }
}
