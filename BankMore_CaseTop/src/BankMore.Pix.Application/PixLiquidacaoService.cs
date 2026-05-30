using BankMore.Pix.Domain;
using BankMore.Pix.Infrastructure;

namespace BankMore.Pix.Application;

/// <summary>
/// Serviço de aplicação central da liquidação PIX. Orquestra o fluxo completo:
///
///   1. Resolve a chave no DICT (bacen-sim) → cpfDestino, ispbDestino, nome
///   2. Gera EndToEndId
///   3. Monta pacs.008 e envia ao SPI
///   4. Lê pacs.002: ACSC → liquida movimentos (D origem / C destino) | RJCT → rejeita
///   5. Persiste a state machine + as mensagens ISO (auditoria)
///
/// Reusado por TODOS os fluxos de iniciação (manual, QR, NFC, automático, Open Finance)
/// — eles só variam no TipoIniciacao e na origem da chave/valor.
/// </summary>
public sealed class PixLiquidacaoService
{
    private const string IspbBankMore = "12345678";

    private readonly IPixRepository _repo;
    private readonly IDictClient _dict;
    private readonly ISpiClient _spi;

    public PixLiquidacaoService(IPixRepository repo, IDictClient dict, ISpiClient spi)
    {
        _repo = repo;
        _dict = dict;
        _spi = spi;
    }

    public async Task<PixPagamento> LiquidarAsync(
        string cpfOrigem, string chaveDestino, decimal valor,
        TipoIniciacao tipo, string correlationId, string? txid, CancellationToken ct)
    {
        var agora = DateTimeOffset.UtcNow;
        var e2e = EndToEndId.Gerar(IspbBankMore, agora);

        var pgto = new PixPagamento
        {
            E2eId = e2e, CpfOrigem = cpfOrigem, ChaveDestino = chaveDestino, Valor = valor,
            TipoIniciacao = tipo, Txid = txid, CorrelationId = correlationId,
            Status = StatusPagamento.RESOLVENDO_CHAVE, IniciadoEm = agora,
        };
        await _repo.SalvarPagamento(pgto, ct);

        // 1. Resolve chave no DICT
        var resolucao = await _dict.ResolverChave(chaveDestino, ct);
        if (resolucao is null)
        {
            pgto.Status = StatusPagamento.REJEITADO;
            pgto.MotivoRejeicao = "CHAVE_NAO_ENCONTRADA_DICT";
            await _repo.AtualizarPagamento(pgto, ct);
            return pgto;
        }
        pgto.CpfDestino = resolucao.CpfTitular;
        pgto.IspbDestino = resolucao.Ispb;

        // 2. Auto-transferência é bloqueada (compliance)
        if (pgto.CpfDestino == cpfOrigem)
        {
            pgto.Status = StatusPagamento.REJEITADO;
            pgto.MotivoRejeicao = "AUTO_TRANSFERENCIA";
            await _repo.AtualizarPagamento(pgto, ct);
            return pgto;
        }

        // 3. Monta pacs.008 e envia ao SPI
        var msgId = "M" + Guid.NewGuid().ToString("N")[..20];
        var pacs008 = Pacs008Builder.Build(
            msgId, e2e, IspbBankMore, resolucao.Ispb, cpfOrigem, resolucao.CpfTitular, valor, agora);
        pgto.Pacs008Xml = pacs008;
        pgto.Status = StatusPagamento.LIQUIDANDO;
        await _repo.AtualizarPagamento(pgto, ct);

        var liq = await _spi.EnviarPacs008(pacs008, ct);
        pgto.Pacs002Xml = liq.Pacs002Xml;

        if (!liq.Sucesso)
        {
            pgto.Status = StatusPagamento.REJEITADO;
            pgto.MotivoRejeicao = $"SPI_{liq.ReasonCode}";
            await _repo.AtualizarPagamento(pgto, ct);
            return pgto;
        }

        // 4. Liquidou no SPI → efetiva os movimentos contábeis (atômico)
        await _repo.LiquidarMovimentos(cpfOrigem, pgto.CpfDestino, valor, e2e, ct);
        pgto.Status = StatusPagamento.LIQUIDADO;
        pgto.LiquidadoEm = DateTimeOffset.UtcNow;
        await _repo.AtualizarPagamento(pgto, ct);
        return pgto;
    }
}
