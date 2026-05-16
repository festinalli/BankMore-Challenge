using KafkaFlow;
using Dapper;
using Npgsql;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using BankMore.Tarifas.Worker.Services;

namespace BankMore.Tarifas.Worker.Handlers
{
    /// <summary>
    /// Efetiva uma transferência APROVADA pelo PyFlink:
    ///   1. Idempotência por <c>id</c> da transferência (replay-safe).
    ///   2. Validação de saldo (Sprint 4.A) — se insuficiente, marca COMPENSADA.
    ///   3. Movimento D na origem (valor da transferência).
    ///   4. Movimento D na origem (categoria=TARIFA) se houver taxa.
    ///   5. Movimento C no destino.
    ///   6. Registro auxiliar em <c>tarifa</c> (auditoria).
    ///   7. Atualiza <c>transferencia.status='EFETIVADA'</c>.
    ///   8. Sprint 4.B — atualiza feature store Redis (count_1h, valores_24h, valores_30d).
    /// Tudo dentro de UMA transação Postgres + commit fire-and-forget no Redis.
    /// </summary>
    public class TarifaConsumer(
        IConfiguration configuration,
        ILogger<TarifaConsumer> logger,
        FeatureStore featureStore)
        : IMessageHandler<TransferenciaAprovadaMessage>
    {
        public async Task Handle(IMessageContext context, TransferenciaAprovadaMessage message)
        {
            var connectionString = configuration.GetConnectionString("DefaultConnection")
                ?? throw new InvalidOperationException("ConnectionStrings:DefaultConnection ausente");

            await using var connection = new NpgsqlConnection(connectionString);
            await connection.OpenAsync();
            await using var tx = await connection.BeginTransactionAsync();

            try
            {
                // 1) Idempotência: se já processamos esse id, ignora
                var jaProcessado = await connection.ExecuteScalarAsync<int>(
                    "SELECT COUNT(1) FROM idempotencia WHERE chave_idempotencia = @id",
                    new { id = message.Id }, tx);

                if (jaProcessado > 0)
                {
                    logger.LogInformation("Mensagem {Id} já processada — ignorando", message.Id);
                    await tx.CommitAsync();
                    return;
                }

                // 2) Resolver contas
                var contaOrigem = await connection.QueryFirstOrDefaultAsync<(string idcontacorrente, int numero)>(
                    "SELECT idcontacorrente, numero FROM contacorrente WHERE cpf = @cpf",
                    new { cpf = message.CpfOrigem }, tx);

                var contaDestino = await connection.QueryFirstOrDefaultAsync<(string idcontacorrente, int numero)>(
                    "SELECT idcontacorrente, numero FROM contacorrente WHERE cpf = @cpf",
                    new { cpf = message.CpfDestino }, tx);

                if (contaOrigem.idcontacorrente is null || contaDestino.idcontacorrente is null)
                {
                    logger.LogError("Conta(s) não encontrada(s): origem={Origem} destino={Destino}",
                        message.CpfOrigem, message.CpfDestino);
                    await tx.RollbackAsync();
                    return;
                }

                // 2.5) Sprint 4.A — validação de saldo na origem (FOR UPDATE pra evitar
                // race condition se duas transferências aprovadas chegarem simultaneamente
                // do mesmo CPF — exemplo: uma do PyFlink e outra de outro produtor)
                var totalDebito = message.Valor + message.Taxa;
                var saldoOrigem = await connection.ExecuteScalarAsync<decimal>(@"
                    SELECT COALESCE(SUM(CASE WHEN tipomovimento='C' THEN valor ELSE -valor END), 0)
                    FROM movimento
                    WHERE idcontacorrente = @id",
                    new { id = contaOrigem.idcontacorrente }, tx);

                if (saldoOrigem < totalDebito)
                {
                    // Saldo insuficiente: marca transferência como COMPENSADA, registra
                    // idempotência (não reprocessar), e segue. O cliente já viu SOLICITADA
                    // na API; precisa olhar /transferencia/{id} pra ver status final.
                    await connection.ExecuteAsync(@"
                        UPDATE transferencia
                           SET status='COMPENSADA', motivo='SALDO_INSUFICIENTE',
                               decidida_em=@data, efetivada_em=@data
                         WHERE id=@id AND status IN ('SOLICITADA', 'APROVADA')",
                        new { id = message.Id, data = DateTime.UtcNow }, tx);

                    await connection.ExecuteAsync(@"
                        INSERT INTO idempotencia (chave_idempotencia, requisicao, resultado, data_processamento)
                        VALUES (@id, @req, 'COMPENSADA_SALDO', @data)",
                        new { id = message.Id, req = message.CorrelationId, data = DateTime.UtcNow }, tx);

                    await tx.CommitAsync();

                    logger.LogWarning(
                        "Compensada {Id}: SALDO_INSUFICIENTE saldo={Saldo:F2} debito={Debito:F2} cpf={Cpf}",
                        message.Id, saldoOrigem, totalDebito, Mask(message.CpfOrigem));
                    return;
                }

                var agora = DateTime.UtcNow;
                const string sqlMovimento = @"
                    INSERT INTO movimento (idmovimento, idcontacorrente, numeroconta, datamovimento, tipomovimento, valor, categoria, transferencia_id)
                    VALUES (@Id, @IdConta, @NumConta, @Data, @Tipo, @Valor, @Categoria, @TransfId)";

                // 3) Movimento D na origem (valor da transferência)
                await connection.ExecuteAsync(sqlMovimento, new
                {
                    Id = Guid.NewGuid().ToString(),
                    IdConta = contaOrigem.idcontacorrente,
                    NumConta = contaOrigem.numero,
                    Data = agora,
                    Tipo = "D",
                    Valor = message.Valor,
                    Categoria = "TRANSFERENCIA",
                    TransfId = message.Id
                }, tx);

                // 4) Movimento D categoria=TARIFA (entra no SUM do saldo)
                if (message.Taxa > 0)
                {
                    await connection.ExecuteAsync(sqlMovimento, new
                    {
                        Id = Guid.NewGuid().ToString(),
                        IdConta = contaOrigem.idcontacorrente,
                        NumConta = contaOrigem.numero,
                        Data = agora,
                        Tipo = "D",
                        Valor = message.Taxa,
                        Categoria = "TARIFA",
                        TransfId = message.Id
                    }, tx);

                    // Auditoria em tarifa
                    await connection.ExecuteAsync(@"
                        INSERT INTO tarifa (id, idcontacorrente, numeroconta, valor, dataprocessamento, tipotransferencia, transferencia_id)
                        VALUES (@Id, @IdConta, @NumConta, @Valor, @Data, @Tipo, @TransfId)",
                        new
                        {
                            Id = Guid.NewGuid().ToString(),
                            IdConta = contaOrigem.idcontacorrente,
                            NumConta = contaOrigem.numero,
                            Valor = message.Taxa,
                            Data = agora,
                            Tipo = TipoTransferenciaInt(message.Tipo),
                            TransfId = message.Id
                        }, tx);
                }

                // 5) Movimento C no destino
                await connection.ExecuteAsync(sqlMovimento, new
                {
                    Id = Guid.NewGuid().ToString(),
                    IdConta = contaDestino.idcontacorrente,
                    NumConta = contaDestino.numero,
                    Data = agora,
                    Tipo = "C",
                    Valor = message.Valor,
                    Categoria = "TRANSFERENCIA",
                    TransfId = message.Id
                }, tx);

                // 6) Marca idempotência
                await connection.ExecuteAsync(@"
                    INSERT INTO idempotencia (chave_idempotencia, requisicao, resultado, data_processamento)
                    VALUES (@id, @req, 'EFETIVADA', @data)",
                    new { id = message.Id, req = message.CorrelationId, data = agora }, tx);

                // 7) Atualiza status na tabela transferencia (se a linha existir)
                await connection.ExecuteAsync(@"
                    UPDATE transferencia SET status='EFETIVADA', efetivada_em=@data WHERE id=@id",
                    new { id = message.Id, data = agora }, tx);

                await tx.CommitAsync();

                logger.LogInformation(
                    "Efetivada {Id}: {Tipo} R$ {Valor} (taxa R$ {Taxa}) origem={CpfO} destino={CpfD}",
                    message.Id, message.Tipo, message.Valor, message.Taxa,
                    Mask(message.CpfOrigem), Mask(message.CpfDestino));

                // Sprint 4.B — atualiza feature store APÓS commit no Postgres.
                // Best-effort: erro aqui é loggado mas não rollback (transação já fechou).
                await featureStore.RegistrarTransferenciaEfetivada(
                    message.CpfOrigem, message.Valor, agora, message.Id);
            }
            catch (Exception ex)
            {
                await tx.RollbackAsync();
                logger.LogError(ex, "Falha ao efetivar transferência {Id}", message.Id);
                throw; // KafkaFlow vai retry
            }
        }

        private static int TipoTransferenciaInt(string tipo) => tipo?.ToUpperInvariant() switch
        {
            "PIX" => 0,
            "TED" => 1,
            "TEF" => 2,
            _ => 0
        };

        private static string Mask(string cpf) =>
            string.IsNullOrEmpty(cpf) || cpf.Length < 4 ? "***" : cpf[..3] + "***";
    }

    /// <summary>
    /// Evento emitido pelo PyFlink em <c>transferencia.aprovada</c>.
    /// Sprint 1: até o Flink existir, um "auto-approver" copia transferencia.solicitada → transferencia.aprovada.
    /// </summary>
    public class TransferenciaAprovadaMessage
    {
        public string Id { get; set; } = string.Empty;
        public string CorrelationId { get; set; } = string.Empty;
        public string CpfOrigem { get; set; } = string.Empty;
        public string CpfDestino { get; set; } = string.Empty;
        public decimal Valor { get; set; }
        public decimal Taxa { get; set; }
        public string Tipo { get; set; } = string.Empty;
        public long Timestamp { get; set; }
    }
}
