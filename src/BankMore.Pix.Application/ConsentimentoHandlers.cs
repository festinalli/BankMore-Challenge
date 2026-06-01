using BankMore.Pix.Domain;
using MediatR;

namespace BankMore.Pix.Application;

public sealed record ConsentimentoResult(Guid Id, string Status, DateTimeOffset? ProximaCobranca);

/// <summary>
/// Cria consentimento de PIX Automático (recorrência autorizada, lançamento jun/2025)
/// ou de Open Finance (iniciação por terceiro/TPP). Estado inicial CRIADO →
/// precisa AUTORIZADO pelo pagador antes de gerar cobranças.
/// </summary>
public sealed record CriarConsentimentoCommand(
    TipoConsentimento Tipo, string CpfPagador, string ChaveRecebedor,
    decimal? ValorFixo, decimal? ValorMaximo, string? Periodicidade,
    DateOnly? DataInicio, DateOnly? DataFim, string? IdTerceiro) : IRequest<ConsentimentoResult>;

public sealed class CriarConsentimentoHandler : IRequestHandler<CriarConsentimentoCommand, ConsentimentoResult>
{
    private readonly IPixRepository _repo;
    public CriarConsentimentoHandler(IPixRepository repo) => _repo = repo;

    public async Task<ConsentimentoResult> Handle(CriarConsentimentoCommand cmd, CancellationToken ct)
    {
        var c = new PixConsentimento
        {
            Tipo = cmd.Tipo, CpfPagador = cmd.CpfPagador, ChaveRecebedor = cmd.ChaveRecebedor,
            ValorFixo = cmd.ValorFixo, ValorMaximo = cmd.ValorMaximo, Periodicidade = cmd.Periodicidade,
            DataInicio = cmd.DataInicio, DataFim = cmd.DataFim, IdTerceiro = cmd.IdTerceiro,
            Status = StatusConsentimento.CRIADO,
        };
        await _repo.SalvarConsentimento(c, ct);
        return new ConsentimentoResult(c.Id, c.Status.ToString(), null);
    }
}

/// <summary>Pagador autoriza o consentimento → agenda a 1ª cobrança recorrente.</summary>
public sealed record AutorizarConsentimentoCommand(Guid ConsentimentoId) : IRequest<ConsentimentoResult>;

public sealed class AutorizarConsentimentoHandler : IRequestHandler<AutorizarConsentimentoCommand, ConsentimentoResult>
{
    private readonly IPixRepository _repo;
    public AutorizarConsentimentoHandler(IPixRepository repo) => _repo = repo;

    public async Task<ConsentimentoResult> Handle(AutorizarConsentimentoCommand cmd, CancellationToken ct)
    {
        var c = await _repo.ObterConsentimento(cmd.ConsentimentoId, ct);
        if (c is null)
            return new ConsentimentoResult(Guid.Empty, "ERRO", null);

        c.Status = StatusConsentimento.AUTORIZADO;
        c.AutorizadoEm = DateTimeOffset.UtcNow;
        // PIX Automático: agenda a 1ª cobrança já (a recorrência reagenda no scheduler).
        // Open Finance (pagamento único iniciado por TPP): cobra imediatamente.
        c.ProximaCobranca = DateTimeOffset.UtcNow;
        await _repo.AtualizarConsentimento(c, ct);
        return new ConsentimentoResult(c.Id, c.Status.ToString(), c.ProximaCobranca);
    }
}

/// <summary>
/// Executa uma cobrança de um consentimento (chamado pelo scheduler de recorrência
/// ou pela iniciação Open Finance). Liquida e reagenda a próxima conforme periodicidade.
/// </summary>
public sealed record ExecutarCobrancaConsentimentoCommand(Guid ConsentimentoId) : IRequest<ResultadoPagamento>;

public sealed class ExecutarCobrancaConsentimentoHandler : IRequestHandler<ExecutarCobrancaConsentimentoCommand, ResultadoPagamento>
{
    private readonly IPixRepository _repo;
    private readonly PixLiquidacaoService _liq;

    public ExecutarCobrancaConsentimentoHandler(IPixRepository repo, PixLiquidacaoService liq)
    {
        _repo = repo;
        _liq = liq;
    }

    public async Task<ResultadoPagamento> Handle(ExecutarCobrancaConsentimentoCommand cmd, CancellationToken ct)
    {
        var c = await _repo.ObterConsentimento(cmd.ConsentimentoId, ct);
        if (c is null || c.Status != StatusConsentimento.AUTORIZADO)
            return new ResultadoPagamento(Guid.Empty, "", "REJEITADO", "CONSENTIMENTO_INVALIDO", 0, null, "AUTOMATICO");

        var valor = c.ValorFixo ?? c.ValorMaximo ?? 0;
        var tipo = c.Tipo == TipoConsentimento.AUTOMATICO ? TipoIniciacao.AUTOMATICO : TipoIniciacao.OPEN_FINANCE;

        var p = await _liq.LiquidarAsync(
            c.CpfPagador, c.ChaveRecebedor, valor, tipo,
            "consent-" + c.Id.ToString("N")[..12], null, ct);

        // Reagenda recorrência (PIX Automático) ou consome (Open Finance pagamento único)
        if (c.Tipo == TipoConsentimento.AUTOMATICO && c.Periodicidade is not null)
        {
            c.ProximaCobranca = ProximaData(DateTimeOffset.UtcNow, c.Periodicidade);
            if (c.DataFim is { } fim && DateOnly.FromDateTime(c.ProximaCobranca.Value.UtcDateTime) > fim)
                c.Status = StatusConsentimento.CONSUMIDO;
        }
        else
        {
            c.Status = StatusConsentimento.CONSUMIDO;
            c.ProximaCobranca = null;
        }
        await _repo.AtualizarConsentimento(c, ct);

        return IniciarPagamentoHandler.ToResultado(p);
    }

    private static DateTimeOffset ProximaData(DateTimeOffset de, string periodicidade) => periodicidade switch
    {
        "SEMANAL" => de.AddDays(7),
        "MENSAL" => de.AddMonths(1),
        "ANUAL" => de.AddYears(1),
        _ => de.AddMonths(1),
    };
}
