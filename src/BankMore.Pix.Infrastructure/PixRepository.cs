using BankMore.Pix.Domain;
using Dapper;
using Npgsql;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// Repositório do bounded context PIX (Dapper + Npgsql).
///
/// A liquidação cria movimentos 'D' (origem) e 'C' (destino) na MESMA transação —
/// o saldo é derivado de SUM(movimento) na view saldo_conta, então a atomicidade
/// do par débito/crédito é o que garante consistência contábil.
/// </summary>
public sealed class PixRepository : IPixRepository
{
    private readonly string _cs;
    public PixRepository(string connectionString) => _cs = connectionString;

    private NpgsqlConnection Db() => new(_cs);

    // ---------------- Chaves ----------------
    public async Task<PixChave?> ObterChaveLocal(string valorChave, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"SELECT id, tipo, valor_chave AS ValorChave, idcontacorrente AS IdContaCorrente,
                                    ispb, status, criado_em AS CriadoEm
                             FROM pix_chave WHERE valor_chave = @valorChave";
        var row = await db.QueryFirstOrDefaultAsync(new CommandDefinition(sql, new { valorChave }, cancellationToken: ct));
        if (row is null) return null;
        return new PixChave
        {
            Id = row.id, Tipo = Enum.Parse<TipoChave>((string)row.tipo), ValorChave = row.valorchave,
            IdContaCorrente = row.idcontacorrente, Ispb = row.ispb, Status = row.status, CriadoEm = row.criadoem
        };
    }

    public async Task SalvarChave(PixChave c, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_chave (id, tipo, valor_chave, idcontacorrente, ispb, status, criado_em)
                             VALUES (@Id, @Tipo, @ValorChave, @IdContaCorrente, @Ispb, @Status, @CriadoEm)
                             ON CONFLICT (valor_chave) DO NOTHING";
        await db.ExecuteAsync(new CommandDefinition(sql, new
        {
            c.Id, Tipo = c.Tipo.ToString(), c.ValorChave, c.IdContaCorrente, c.Ispb, c.Status, c.CriadoEm
        }, cancellationToken: ct));
    }

    public async Task<IReadOnlyList<PixChave>> ListarChavesPorConta(string idContaCorrente, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"SELECT id, tipo, valor_chave AS ValorChave, idcontacorrente AS IdContaCorrente,
                                    ispb, status, criado_em AS CriadoEm
                             FROM pix_chave WHERE idcontacorrente = @idContaCorrente ORDER BY criado_em";
        var rows = await db.QueryAsync(new CommandDefinition(sql, new { idContaCorrente }, cancellationToken: ct));
        return rows.Select(r => new PixChave
        {
            Id = r.id, Tipo = Enum.Parse<TipoChave>((string)r.tipo), ValorChave = r.valorchave,
            IdContaCorrente = r.idcontacorrente, Ispb = r.ispb, Status = r.status, CriadoEm = r.criadoem
        }).ToList();
    }

    // ---------------- Pagamentos ----------------
    public async Task SalvarPagamento(PixPagamento p, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_pagamento
            (id, e2eid, cpf_origem, chave_destino, cpf_destino, ispb_destino, valor, tipo_iniciacao,
             txid, status, motivo_rejeicao, score_fraude, modelo_versao, pacs008_xml, pacs002_xml,
             correlation_id, iniciado_em, liquidado_em)
            VALUES (@Id, @E2eId, @CpfOrigem, @ChaveDestino, @CpfDestino, @IspbDestino, @Valor, @TipoIniciacao,
             @Txid, @Status, @MotivoRejeicao, @ScoreFraude, @ModeloVersao, @Pacs008Xml, @Pacs002Xml,
             @CorrelationId, @IniciadoEm, @LiquidadoEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, Map(p), cancellationToken: ct));
    }

    public async Task AtualizarPagamento(PixPagamento p, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"UPDATE pix_pagamento SET
                                chave_destino=@ChaveDestino, cpf_destino=@CpfDestino, ispb_destino=@IspbDestino,
                                txid=@Txid, status=@Status, motivo_rejeicao=@MotivoRejeicao,
                                score_fraude=@ScoreFraude, modelo_versao=@ModeloVersao,
                                pacs008_xml=@Pacs008Xml, pacs002_xml=@Pacs002Xml, liquidado_em=@LiquidadoEm
                             WHERE id=@Id";
        await db.ExecuteAsync(new CommandDefinition(sql, Map(p), cancellationToken: ct));
    }

    private static object Map(PixPagamento p) => new
    {
        p.Id, p.E2eId, p.CpfOrigem, p.ChaveDestino, p.CpfDestino, p.IspbDestino, p.Valor,
        TipoIniciacao = p.TipoIniciacao.ToString(), p.Txid, Status = p.Status.ToString(),
        p.MotivoRejeicao, p.ScoreFraude, p.ModeloVersao, p.Pacs008Xml, p.Pacs002Xml,
        p.CorrelationId, p.IniciadoEm, p.LiquidadoEm
    };

    public async Task<PixPagamento?> ObterPagamento(Guid id, CancellationToken ct)
    {
        await using var db = Db();
        return MapBack(await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_pagamento WHERE id=@id", new { id }, cancellationToken: ct)));
    }

    public async Task<PixPagamento?> ObterPagamentoPorE2e(string e2eId, CancellationToken ct)
    {
        await using var db = Db();
        return MapBack(await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_pagamento WHERE e2eid=@e2eId", new { e2eId }, cancellationToken: ct)));
    }

    public async Task<int> ContarPagamentosRecentes(string cpfOrigem, TimeSpan janela, CancellationToken ct)
    {
        await using var db = Db();
        var desde = DateTimeOffset.UtcNow - janela;
        return await db.ExecuteScalarAsync<int>(new CommandDefinition(
            "SELECT COUNT(*) FROM pix_pagamento WHERE cpf_origem=@cpfOrigem AND iniciado_em >= @desde",
            new { cpfOrigem, desde }, cancellationToken: ct));
    }

    private static PixPagamento? MapBack(dynamic? r)
    {
        if (r is null) return null;
        return new PixPagamento
        {
            Id = r.id, E2eId = r.e2eid, CpfOrigem = r.cpf_origem, ChaveDestino = r.chave_destino,
            CpfDestino = r.cpf_destino, IspbDestino = r.ispb_destino, Valor = r.valor,
            TipoIniciacao = Enum.Parse<TipoIniciacao>((string)r.tipo_iniciacao), Txid = r.txid,
            Status = Enum.Parse<StatusPagamento>((string)r.status), MotivoRejeicao = r.motivo_rejeicao,
            ScoreFraude = r.score_fraude, ModeloVersao = r.modelo_versao,
            Pacs008Xml = r.pacs008_xml, Pacs002Xml = r.pacs002_xml, CorrelationId = r.correlation_id,
            IniciadoEm = r.iniciado_em, LiquidadoEm = r.liquidado_em
        };
    }

    // ---------------- Liquidação contábil (atômica) ----------------
    public async Task LiquidarMovimentos(string cpfOrigem, string? cpfDestino, decimal valor, string e2eId, CancellationToken ct)
    {
        await using var db = Db();
        await db.OpenAsync(ct);
        await using var tx = await db.BeginTransactionAsync(ct);

        var origem = await ContaPorCpf(db, tx, cpfOrigem, ct);
        await InserirMovimento(db, tx, origem, 'D', valor, e2eId, ct);

        // Crédito ao destino só se for conta deste PSP (intra-BankMore). Inter-PSP,
        // o crédito é feito pelo PSP destino — aqui o débito origem + liquidação SPI bastam.
        if (cpfDestino is not null)
        {
            var destino = await ContaPorCpf(db, tx, cpfDestino, ct);
            if (destino is not null)
                await InserirMovimento(db, tx, destino, 'C', valor, e2eId, ct);
        }

        await tx.CommitAsync(ct);
    }

    public async Task EstornarMovimentos(string cpfOrigem, string? cpfDestino, decimal valor, string e2eId, CancellationToken ct)
    {
        // Devolução MED: credita de volta a origem, debita o destino (se intra-PSP).
        await using var db = Db();
        await db.OpenAsync(ct);
        await using var tx = await db.BeginTransactionAsync(ct);

        var origem = await ContaPorCpf(db, tx, cpfOrigem, ct);
        await InserirMovimento(db, tx, origem, 'C', valor, e2eId + "-DEV", ct);

        if (cpfDestino is not null)
        {
            var destino = await ContaPorCpf(db, tx, cpfDestino, ct);
            if (destino is not null)
                await InserirMovimento(db, tx, destino, 'D', valor, e2eId + "-DEV", ct);
        }

        await tx.CommitAsync(ct);
    }

    private static async Task<(string Id, int Numero)?> ContaPorCpf(NpgsqlConnection db, System.Data.Common.DbTransaction tx, string cpf, CancellationToken ct)
    {
        var row = await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT idcontacorrente, numero FROM contacorrente WHERE cpf=@cpf", new { cpf }, tx, cancellationToken: ct));
        if (row is null) return null;
        return ((string)row.idcontacorrente, (int)row.numero);
    }

    private static async Task InserirMovimento(NpgsqlConnection db, System.Data.Common.DbTransaction tx,
        (string Id, int Numero)? conta, char tipo, decimal valor, string e2eId, CancellationToken ct)
    {
        if (conta is null) return;
        const string sql = @"INSERT INTO movimento (idmovimento, idcontacorrente, numeroconta, datamovimento,
                                tipomovimento, valor, categoria, transferencia_id)
                             VALUES (@id, @conta, @numero, NOW(), @tipo, @valor, 'PIX', @e2e)";
        await db.ExecuteAsync(new CommandDefinition(sql, new
        {
            id = Guid.NewGuid().ToString(), conta = conta.Value.Id, numero = conta.Value.Numero,
            tipo = tipo.ToString(), valor, e2e = e2eId
        }, tx, cancellationToken: ct));
    }

    public async Task<string?> ObterIdContaPorCpf(string cpf, CancellationToken ct)
    {
        await using var db = Db();
        return await db.QueryFirstOrDefaultAsync<string?>(new CommandDefinition(
            "SELECT idcontacorrente FROM contacorrente WHERE cpf=@cpf", new { cpf }, cancellationToken: ct));
    }

    public async Task<string?> ObterNomePorCpf(string cpf, CancellationToken ct)
    {
        await using var db = Db();
        return await db.QueryFirstOrDefaultAsync<string?>(new CommandDefinition(
            "SELECT nome FROM contacorrente WHERE cpf=@cpf", new { cpf }, cancellationToken: ct));
    }

    public async Task<string?> ObterCpfPorIdConta(string idContaCorrente, CancellationToken ct)
    {
        await using var db = Db();
        return await db.QueryFirstOrDefaultAsync<string?>(new CommandDefinition(
            "SELECT cpf FROM contacorrente WHERE idcontacorrente=@idContaCorrente",
            new { idContaCorrente }, cancellationToken: ct));
    }

    // ---------------- QR Code ----------------
    public async Task SalvarQrCode(PixQrCode qr, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_qrcode (id, txid, tipo, chave, valor, payload_emv, descricao, status, vencimento, criado_em)
                             VALUES (@Id, @Txid, @Tipo, @Chave, @Valor, @PayloadEmv, @Descricao, @Status, @Vencimento, @CriadoEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, new
        {
            qr.Id, qr.Txid, Tipo = qr.Tipo.ToString(), qr.Chave, qr.Valor, qr.PayloadEmv,
            qr.Descricao, qr.Status, qr.Vencimento, qr.CriadoEm
        }, cancellationToken: ct));
    }

    public async Task<PixQrCode?> ObterQrCodePorTxid(string txid, CancellationToken ct)
    {
        await using var db = Db();
        var r = await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_qrcode WHERE txid=@txid", new { txid }, cancellationToken: ct));
        if (r is null) return null;
        return new PixQrCode
        {
            Id = r.id, Txid = r.txid, Tipo = Enum.Parse<TipoQrCode>((string)r.tipo), Chave = r.chave,
            Valor = r.valor, PayloadEmv = r.payload_emv, Descricao = r.descricao, Status = r.status,
            Vencimento = r.vencimento, CriadoEm = r.criado_em
        };
    }

    public async Task AtualizarStatusQrCode(string txid, string status, CancellationToken ct)
    {
        await using var db = Db();
        await db.ExecuteAsync(new CommandDefinition(
            "UPDATE pix_qrcode SET status=@status WHERE txid=@txid", new { status, txid }, cancellationToken: ct));
    }

    // ---------------- MED ----------------
    public async Task SalvarDevolucao(PixDevolucao d, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_devolucao (id, devolution_id, pagamento_id, valor, motivo, status,
                                pacs004_xml, solicitado_em, prazo_limite, resolvido_em)
                             VALUES (@Id, @DevolutionId, @PagamentoId, @Valor, @Motivo, @Status,
                                @Pacs004Xml, @SolicitadoEm, @PrazoLimite, @ResolvidoEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, MapDev(d), cancellationToken: ct));
    }

    public async Task AtualizarDevolucao(PixDevolucao d, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"UPDATE pix_devolucao SET status=@Status, pacs004_xml=@Pacs004Xml, resolvido_em=@ResolvidoEm
                             WHERE id=@Id";
        await db.ExecuteAsync(new CommandDefinition(sql, MapDev(d), cancellationToken: ct));
    }

    private static object MapDev(PixDevolucao d) => new
    {
        d.Id, d.DevolutionId, d.PagamentoId, d.Valor, Motivo = d.Motivo.ToString(),
        Status = d.Status.ToString(), d.Pacs004Xml, d.SolicitadoEm, d.PrazoLimite, d.ResolvidoEm
    };

    public async Task<PixDevolucao?> ObterDevolucao(Guid id, CancellationToken ct)
    {
        await using var db = Db();
        var r = await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_devolucao WHERE id=@id", new { id }, cancellationToken: ct));
        if (r is null) return null;
        return new PixDevolucao
        {
            Id = r.id, DevolutionId = r.devolution_id, PagamentoId = r.pagamento_id, Valor = r.valor,
            Motivo = Enum.Parse<MotivoDevolucao>((string)r.motivo), Status = Enum.Parse<StatusDevolucao>((string)r.status),
            Pacs004Xml = r.pacs004_xml, SolicitadoEm = r.solicitado_em, PrazoLimite = r.prazo_limite, ResolvidoEm = r.resolvido_em
        };
    }

    // ---------------- Consentimento ----------------
    public async Task SalvarConsentimento(PixConsentimento c, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_consentimento (id, tipo, cpf_pagador, chave_recebedor, valor_fixo,
                                valor_maximo, periodicidade, data_inicio, data_fim, status, proxima_cobranca,
                                id_terceiro, criado_em, autorizado_em)
                             VALUES (@Id, @Tipo, @CpfPagador, @ChaveRecebedor, @ValorFixo, @ValorMaximo,
                                @Periodicidade, @DataInicio, @DataFim, @Status, @ProximaCobranca, @IdTerceiro,
                                @CriadoEm, @AutorizadoEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, MapCon(c), cancellationToken: ct));
    }

    public async Task AtualizarConsentimento(PixConsentimento c, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"UPDATE pix_consentimento SET status=@Status, proxima_cobranca=@ProximaCobranca,
                                autorizado_em=@AutorizadoEm WHERE id=@Id";
        await db.ExecuteAsync(new CommandDefinition(sql, MapCon(c), cancellationToken: ct));
    }

    private static object MapCon(PixConsentimento c) => new
    {
        c.Id, Tipo = c.Tipo.ToString(), c.CpfPagador, c.ChaveRecebedor, c.ValorFixo, c.ValorMaximo,
        c.Periodicidade, DataInicio = c.DataInicio?.ToDateTime(TimeOnly.MinValue),
        DataFim = c.DataFim?.ToDateTime(TimeOnly.MinValue), Status = c.Status.ToString(),
        c.ProximaCobranca, c.IdTerceiro, c.CriadoEm, c.AutorizadoEm
    };

    public async Task<PixConsentimento?> ObterConsentimento(Guid id, CancellationToken ct)
    {
        await using var db = Db();
        var r = await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_consentimento WHERE id=@id", new { id }, cancellationToken: ct));
        return r is null ? null : MapConBack(r);
    }

    public async Task<IReadOnlyList<PixConsentimento>> ListarConsentimentosVencidos(DateTimeOffset agora, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"SELECT * FROM pix_consentimento
                             WHERE status='AUTORIZADO' AND proxima_cobranca IS NOT NULL AND proxima_cobranca <= @agora";
        var rows = await db.QueryAsync(new CommandDefinition(sql, new { agora }, cancellationToken: ct));
        return rows.Select(r => (PixConsentimento)MapConBack(r)).ToList();
    }

    private static PixConsentimento MapConBack(dynamic r) => new()
    {
        Id = r.id, Tipo = Enum.Parse<TipoConsentimento>((string)r.tipo), CpfPagador = r.cpf_pagador,
        ChaveRecebedor = r.chave_recebedor, ValorFixo = r.valor_fixo, ValorMaximo = r.valor_maximo,
        Periodicidade = r.periodicidade,
        DataInicio = r.data_inicio is null ? null : DateOnly.FromDateTime((DateTime)r.data_inicio),
        DataFim = r.data_fim is null ? null : DateOnly.FromDateTime((DateTime)r.data_fim),
        Status = Enum.Parse<StatusConsentimento>((string)r.status), ProximaCobranca = r.proxima_cobranca,
        IdTerceiro = r.id_terceiro, CriadoEm = r.criado_em, AutorizadoEm = r.autorizado_em
    };

    // ---------------- NFC ----------------
    public async Task SalvarNfcToken(PixNfcToken t, CancellationToken ct)
    {
        await using var db = Db();
        const string sql = @"INSERT INTO pix_nfc_token (id, token, idcontacorrente, valor_maximo, status, expira_em, usado_em, criado_em)
                             VALUES (@Id, @Token, @IdContaCorrente, @ValorMaximo, @Status, @ExpiraEm, @UsadoEm, @CriadoEm)";
        await db.ExecuteAsync(new CommandDefinition(sql, new
        {
            t.Id, t.Token, t.IdContaCorrente, t.ValorMaximo, t.Status, t.ExpiraEm, t.UsadoEm, t.CriadoEm
        }, cancellationToken: ct));
    }

    public async Task<PixNfcToken?> ObterNfcToken(string token, CancellationToken ct)
    {
        await using var db = Db();
        var r = await db.QueryFirstOrDefaultAsync(new CommandDefinition(
            "SELECT * FROM pix_nfc_token WHERE token=@token", new { token }, cancellationToken: ct));
        if (r is null) return null;
        return new PixNfcToken
        {
            Id = r.id, Token = r.token, IdContaCorrente = r.idcontacorrente, ValorMaximo = r.valor_maximo,
            Status = r.status, ExpiraEm = r.expira_em, UsadoEm = r.usado_em, CriadoEm = r.criado_em
        };
    }

    public async Task AtualizarNfcToken(PixNfcToken t, CancellationToken ct)
    {
        await using var db = Db();
        await db.ExecuteAsync(new CommandDefinition(
            "UPDATE pix_nfc_token SET status=@Status, usado_em=@UsadoEm WHERE id=@Id",
            new { t.Status, t.UsadoEm, t.Id }, cancellationToken: ct));
    }
}
