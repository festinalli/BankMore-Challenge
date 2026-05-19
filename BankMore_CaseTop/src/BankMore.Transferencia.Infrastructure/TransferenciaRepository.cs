using Dapper;
using Npgsql;
using NpgsqlTypes;
using BankMore.Transferencia.Domain;
using TransferenciaEntity = BankMore.Transferencia.Domain.Transferencia;

namespace BankMore.Transferencia.Infrastructure;

public class TransferenciaRepository : ITransferenciaRepository
{
    private readonly string _connectionString;

    public TransferenciaRepository(string connectionString)
    {
        if (string.IsNullOrWhiteSpace(connectionString))
            throw new ArgumentException("Connection string vazia", nameof(connectionString));
        _connectionString = connectionString;
    }

    public async Task PersistirSolicitadaComOutbox(
        TransferenciaEntity t,
        string topic,
        string payloadJson,
        CancellationToken ct)
    {
        await using var db = new NpgsqlConnection(_connectionString);
        await db.OpenAsync(ct);
        await using var tx = await db.BeginTransactionAsync(ct);

        try
        {
            // 1) transferencia (status=SOLICITADA)
            const string sqlT = @"
                INSERT INTO transferencia
                    (id, correlation_id, cpf_origem, cpf_destino, valor, tipo, status, solicitada_em)
                VALUES
                    (@Id, @CorrelationId, @CpfOrigem, @CpfDestino, @Valor, @Tipo, 'SOLICITADA', @SolicitadaEm)";
            await db.ExecuteAsync(new CommandDefinition(sqlT, t, transaction: tx, cancellationToken: ct));

            // 2) outbox row — payload JSON pra publicação assíncrona pelo OutboxRelay.
            //    Usamos NpgsqlParameter pra forçar o tipo jsonb (Dapper passa como text por default).
            const string sqlO = @"
                INSERT INTO transferencia_outbox (transferencia_id, topic, payload)
                VALUES (@TransferenciaId, @Topic, @Payload::jsonb)";
            await db.ExecuteAsync(new CommandDefinition(sqlO,
                new { TransferenciaId = t.Id, Topic = topic, Payload = payloadJson },
                transaction: tx, cancellationToken: ct));

            await tx.CommitAsync(ct);
        }
        catch
        {
            await tx.RollbackAsync(ct);
            throw;
        }
    }

    public async Task<TransferenciaEntity?> ObterPorId(string id, CancellationToken ct)
    {
        await using var db = new NpgsqlConnection(_connectionString);
        const string sql = @"
            SELECT id, correlation_id AS CorrelationId, cpf_origem AS CpfOrigem, cpf_destino AS CpfDestino,
                   valor, tipo, status, motivo, score_fraude AS ScoreFraude, modelo_versao AS ModeloVersao,
                   solicitada_em AS SolicitadaEm, decidida_em AS DecididaEm, efetivada_em AS EfetivadaEm
            FROM transferencia WHERE id = @id";
        return await db.QueryFirstOrDefaultAsync<TransferenciaEntity>(
            new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<IReadOnlyList<OutboxItem>> LerPendentes(int limite, CancellationToken ct)
    {
        // FOR UPDATE SKIP LOCKED: múltiplos relays podem rodar em paralelo sem colidir
        // (cada um pega lotes distintos). Limite 100 por iteração pra evitar lock longo.
        await using var db = new NpgsqlConnection(_connectionString);
        const string sql = @"
            SELECT id, transferencia_id AS TransferenciaId, topic, payload::text AS PayloadJson, tentativas
            FROM transferencia_outbox
            WHERE publicado_em IS NULL
              AND (ultima_tentativa_em IS NULL OR ultima_tentativa_em < NOW() - INTERVAL '5 seconds' * tentativas)
            ORDER BY criado_em
            LIMIT @limite
            FOR UPDATE SKIP LOCKED";
        var rows = await db.QueryAsync<OutboxItem>(
            new CommandDefinition(sql, new { limite }, cancellationToken: ct));
        return rows.AsList();
    }

    public async Task MarcarPublicado(Guid id, CancellationToken ct)
    {
        await using var db = new NpgsqlConnection(_connectionString);
        const string sql = @"
            UPDATE transferencia_outbox
               SET publicado_em = NOW(), ultima_tentativa_em = NOW()
             WHERE id = @id";
        await db.ExecuteAsync(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task MarcarFalha(Guid id, string erro, CancellationToken ct)
    {
        await using var db = new NpgsqlConnection(_connectionString);
        const string sql = @"
            UPDATE transferencia_outbox
               SET tentativas = tentativas + 1,
                   ultima_tentativa_em = NOW(),
                   ultimo_erro = LEFT(@erro, 500)
             WHERE id = @id";
        await db.ExecuteAsync(new CommandDefinition(sql, new { id, erro }, cancellationToken: ct));
    }
}
