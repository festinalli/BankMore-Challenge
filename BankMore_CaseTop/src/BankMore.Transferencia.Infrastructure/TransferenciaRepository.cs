using Dapper;
using Npgsql;
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

    public async Task PersistirSolicitada(TransferenciaEntity t, CancellationToken ct)
    {
        await using var db = new NpgsqlConnection(_connectionString);
        const string sql = @"
            INSERT INTO transferencia
                (id, correlation_id, cpf_origem, cpf_destino, valor, tipo, status, solicitada_em)
            VALUES
                (@Id, @CorrelationId, @CpfOrigem, @CpfDestino, @Valor, @Tipo, 'SOLICITADA', @SolicitadaEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, t, cancellationToken: ct));
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
}
