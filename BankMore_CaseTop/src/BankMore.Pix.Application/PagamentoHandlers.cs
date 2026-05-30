using BankMore.Pix.Domain;
using MediatR;

namespace BankMore.Pix.Application;

public sealed record ResultadoPagamento(
    Guid Id, string E2eId, string Status, string? Motivo, decimal Valor,
    string? CpfDestino, string TipoIniciacao);

/// <summary>Pagamento PIX por chave (iniciação manual).</summary>
public sealed record IniciarPagamentoCommand(
    string CpfOrigem, string ChaveDestino, decimal Valor, string CorrelationId) : IRequest<ResultadoPagamento>;

public sealed class IniciarPagamentoHandler : IRequestHandler<IniciarPagamentoCommand, ResultadoPagamento>
{
    private readonly PixLiquidacaoService _liq;
    public IniciarPagamentoHandler(PixLiquidacaoService liq) => _liq = liq;

    public async Task<ResultadoPagamento> Handle(IniciarPagamentoCommand cmd, CancellationToken ct)
    {
        if (cmd.Valor <= 0)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "VALOR_INVALIDO", cmd.Valor, null, "MANUAL");

        var p = await _liq.LiquidarAsync(
            cmd.CpfOrigem, cmd.ChaveDestino, cmd.Valor,
            TipoIniciacao.MANUAL, cmd.CorrelationId, null, ct);
        return ToResultado(p);
    }

    internal static ResultadoPagamento ToResultado(PixPagamento p) =>
        new(p.Id, p.E2eId, p.Status.ToString(), p.MotivoRejeicao, p.Valor, p.CpfDestino, p.TipoIniciacao.ToString());
}

/// <summary>Pagamento de um QR Code lido (txid resolve chave/valor).</summary>
public sealed record PagarQrCodeCommand(
    string CpfOrigem, string Txid, decimal? ValorInformado, string CorrelationId) : IRequest<ResultadoPagamento>;

public sealed class PagarQrCodeHandler : IRequestHandler<PagarQrCodeCommand, ResultadoPagamento>
{
    private readonly PixLiquidacaoService _liq;
    private readonly IPixRepository _repo;

    public PagarQrCodeHandler(PixLiquidacaoService liq, IPixRepository repo)
    {
        _liq = liq;
        _repo = repo;
    }

    public async Task<ResultadoPagamento> Handle(PagarQrCodeCommand cmd, CancellationToken ct)
    {
        var qr = await _repo.ObterQrCodePorTxid(cmd.Txid, ct);
        if (qr is null)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "QRCODE_NAO_ENCONTRADO", 0, null, "QRCODE");
        if (qr.Status != "ATIVO")
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", $"QRCODE_{qr.Status}", 0, null, "QRCODE");
        if (qr.Vencimento is { } venc && venc < DateTimeOffset.UtcNow)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "QRCODE_EXPIRADO", 0, null, "QRCODE");

        // Valor: QR com valor fixo manda; valor aberto usa o informado pelo pagador
        var valor = qr.Valor ?? cmd.ValorInformado ?? 0;
        if (valor <= 0)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "VALOR_INVALIDO", 0, null, "QRCODE");

        var tipo = qr.Tipo == TipoQrCode.ESTATICO ? TipoIniciacao.QRCODE_ESTATICO : TipoIniciacao.QRCODE_DINAMICO;
        var p = await _liq.LiquidarAsync(cmd.CpfOrigem, qr.Chave, valor, tipo, cmd.CorrelationId, cmd.Txid, ct);

        // QR dinâmico/CoBV é uso-único: marca PAGO. Estático é reutilizável, fica ATIVO.
        if (p.Status == StatusPagamento.LIQUIDADO && qr.Tipo != TipoQrCode.ESTATICO)
            await _repo.AtualizarStatusQrCode(qr.Txid, "PAGO", ct);

        return IniciarPagamentoHandler.ToResultado(p);
    }
}
