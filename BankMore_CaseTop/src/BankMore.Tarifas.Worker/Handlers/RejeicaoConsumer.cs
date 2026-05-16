using KafkaFlow;
using Dapper;
using Npgsql;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace BankMore.Tarifas.Worker.Handlers;

/// <summary>
/// Marca a tabela <c>transferencia</c> como REJEITADA quando o detector rejeita.
/// Não toca em saldo (a rejeição é antes da efetivação — nada foi debitado).
/// </summary>
public class RejeicaoConsumer(IConfiguration configuration, ILogger<RejeicaoConsumer> logger)
    : IMessageHandler<TransferenciaRejeitadaMessage>
{
    public async Task Handle(IMessageContext context, TransferenciaRejeitadaMessage message)
    {
        var connectionString = configuration.GetConnectionString("DefaultConnection")
            ?? throw new InvalidOperationException("ConnectionStrings:DefaultConnection ausente");

        await using var db = new NpgsqlConnection(connectionString);
        const string sql = @"
            UPDATE transferencia
               SET status='REJEITADA',
                   motivo=@motivo,
                   modelo_versao=@versao,
                   score_fraude=@score,
                   decidida_em=@decididaEm
             WHERE id=@id AND status IN ('SOLICITADA')";

        var motivos = message.Motivos != null && message.Motivos.Length > 0
            ? string.Join(",", message.Motivos)
            : "desconhecido";

        var rows = await db.ExecuteAsync(sql, new
        {
            id = message.Id,
            motivo = motivos,
            versao = message.ModeloVersao ?? "rules-v1",
            score = message.ScoreFraude,
            decididaEm = FromMillis(message.DecididoEm) ?? DateTime.UtcNow
        });

        if (rows == 0)
        {
            logger.LogWarning("Rejeição {Id} sem linha em transferencia (race?)", message.Id);
        }
        else
        {
            logger.LogInformation("Rejeitada {Id}: motivos={Motivos}", message.Id, motivos);
        }
    }

    private static DateTime? FromMillis(long? ms) =>
        ms.HasValue ? DateTimeOffset.FromUnixTimeMilliseconds(ms.Value).UtcDateTime : null;
}

public class TransferenciaRejeitadaMessage
{
    public string Id { get; set; } = string.Empty;
    public string CorrelationId { get; set; } = string.Empty;
    public string CpfOrigem { get; set; } = string.Empty;
    public string CpfDestino { get; set; } = string.Empty;
    public decimal Valor { get; set; }
    public string Tipo { get; set; } = string.Empty;
    public string Decisao { get; set; } = "REJEITADA";
    public string[]? Motivos { get; set; }
    public string? ModeloVersao { get; set; }
    public decimal? ScoreFraude { get; set; }
    public long? DecididoEm { get; set; }
}
