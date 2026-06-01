using System.Security.Cryptography;
using BankMore.Pix.Domain;
using MediatR;

namespace BankMore.Pix.Application;

public sealed record NfcTokenResult(string Token, DateTimeOffset ExpiraEm, decimal ValorMaximo);

/// <summary>
/// PIX por Aproximação (NFC, 2025): o app gera um token efêmero single-use com teto
/// de valor. O token é "aproximado" na maquininha, que inicia o pagamento. Curtíssima
/// validade (default 60s) limita janela de abuso se o device for comprometido.
/// </summary>
public sealed record GerarNfcTokenCommand(string Cpf, decimal ValorMaximo, int TtlSegundos) : IRequest<NfcTokenResult?>;

public sealed class GerarNfcTokenHandler : IRequestHandler<GerarNfcTokenCommand, NfcTokenResult?>
{
    private readonly IPixRepository _repo;
    public GerarNfcTokenHandler(IPixRepository repo) => _repo = repo;

    public async Task<NfcTokenResult?> Handle(GerarNfcTokenCommand cmd, CancellationToken ct)
    {
        var idConta = await _repo.ObterIdContaPorCpf(cmd.Cpf, ct);
        if (idConta is null) return null;

        var ttl = cmd.TtlSegundos is > 0 and <= 300 ? cmd.TtlSegundos : 60;
        var token = "NFC" + Base32(RandomNumberGenerator.GetBytes(15));
        var t = new PixNfcToken
        {
            Token = token, IdContaCorrente = idConta, ValorMaximo = cmd.ValorMaximo,
            Status = "ATIVO", ExpiraEm = DateTimeOffset.UtcNow.AddSeconds(ttl),
        };
        await _repo.SalvarNfcToken(t, ct);
        return new NfcTokenResult(token, t.ExpiraEm, t.ValorMaximo);
    }

    private static string Base32(byte[] b) => Convert.ToHexString(b);
}

/// <summary>Maquininha apresenta o token + chave do recebedor → inicia o PIX.</summary>
public sealed record PagarNfcCommand(
    string Token, string ChaveRecebedor, decimal Valor, string CorrelationId) : IRequest<ResultadoPagamento>;

public sealed class PagarNfcHandler : IRequestHandler<PagarNfcCommand, ResultadoPagamento>
{
    private readonly IPixRepository _repo;
    private readonly PixLiquidacaoService _liq;

    public PagarNfcHandler(IPixRepository repo, PixLiquidacaoService liq)
    {
        _repo = repo;
        _liq = liq;
    }

    public async Task<ResultadoPagamento> Handle(PagarNfcCommand cmd, CancellationToken ct)
    {
        var t = await _repo.ObterNfcToken(cmd.Token, ct);
        if (t is null)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "TOKEN_NFC_INVALIDO", cmd.Valor, null, "NFC");
        if (t.Status != "ATIVO")
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", $"TOKEN_{t.Status}", cmd.Valor, null, "NFC");
        if (t.ExpiraEm < DateTimeOffset.UtcNow)
        {
            t.Status = "EXPIRADO";
            await _repo.AtualizarNfcToken(t, ct);
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "TOKEN_NFC_EXPIRADO", cmd.Valor, null, "NFC");
        }
        if (cmd.Valor > t.ValorMaximo)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "VALOR_ACIMA_TETO_NFC", cmd.Valor, null, "NFC");

        // Descobre o CPF pagador a partir da conta do token
        var cpfOrigem = await _repo.ObterCpfPorIdConta(t.IdContaCorrente, ct);
        if (cpfOrigem is null)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "CONTA_NFC_INVALIDA", cmd.Valor, null, "NFC");

        // Consome o token (single-use) ANTES de liquidar — evita replay
        t.Status = "USADO";
        t.UsadoEm = DateTimeOffset.UtcNow;
        await _repo.AtualizarNfcToken(t, ct);

        var p = await _liq.LiquidarAsync(cpfOrigem, cmd.ChaveRecebedor, cmd.Valor,
            TipoIniciacao.NFC, cmd.CorrelationId, null, ct);
        return IniciarPagamentoHandler.ToResultado(p);
    }
}
