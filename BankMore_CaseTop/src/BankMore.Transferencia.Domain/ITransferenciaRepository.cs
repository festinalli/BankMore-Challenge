using TransferenciaEntity = BankMore.Transferencia.Domain.Transferencia;

namespace BankMore.Transferencia.Domain;

public interface ITransferenciaRepository
{
    /// <summary>Persiste a solicitação com status=SOLICITADA antes de publicar no Kafka.</summary>
    Task PersistirSolicitada(TransferenciaEntity transferencia, CancellationToken ct);

    Task<TransferenciaEntity?> ObterPorId(string id, CancellationToken ct);
}
