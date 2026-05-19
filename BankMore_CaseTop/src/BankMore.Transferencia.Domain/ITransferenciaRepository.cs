using TransferenciaEntity = BankMore.Transferencia.Domain.Transferencia;

namespace BankMore.Transferencia.Domain;

public interface ITransferenciaRepository
{
    /// <summary>
    /// Sprint 5.B — Outbox pattern: persiste a transferência + enfileira o evento
    /// na tabela transferencia_outbox dentro da MESMA transação. Se o relay falhar
    /// depois, a transferência fica SOLICITADA e a row do outbox aguarda retry.
    /// Se a transação roda inteira, ambos commitam atomicamente; se algo falha,
    /// nada é persistido (sem fantasma SOLICITADA órfão).
    /// </summary>
    Task PersistirSolicitadaComOutbox(
        TransferenciaEntity transferencia,
        string topic,
        string payloadJson,
        CancellationToken ct);

    Task<TransferenciaEntity?> ObterPorId(string id, CancellationToken ct);

    // -------- Outbox relay --------
    /// <summary>Lê próximos N eventos não publicados (FOR UPDATE SKIP LOCKED).</summary>
    Task<IReadOnlyList<OutboxItem>> LerPendentes(int limite, CancellationToken ct);

    /// <summary>Marca uma row como publicada.</summary>
    Task MarcarPublicado(Guid id, CancellationToken ct);

    /// <summary>Incrementa tentativas e registra erro (não publicado).</summary>
    Task MarcarFalha(Guid id, string erro, CancellationToken ct);
}

public sealed record OutboxItem(Guid Id, string TransferenciaId, string Topic, string PayloadJson, int Tentativas);
