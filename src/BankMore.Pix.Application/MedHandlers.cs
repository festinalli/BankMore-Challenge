using BankMore.Pix.Domain;
using BankMore.Pix.Infrastructure;
using MediatR;

namespace BankMore.Pix.Application;

public sealed record DevolucaoResult(Guid Id, string DevolutionId, string Status, string? Erro);

/// <summary>
/// MED — solicita devolução de um PIX liquidado. Abre com bloqueio cautelar do
/// recurso (status BLOQUEADO) e prazo SLA: 11 dias pra golpe confirmado, 80 pra análise.
/// </summary>
public sealed record SolicitarDevolucaoCommand(
    Guid PagamentoId, MotivoDevolucao Motivo) : IRequest<DevolucaoResult>;

public sealed class SolicitarDevolucaoHandler : IRequestHandler<SolicitarDevolucaoCommand, DevolucaoResult>
{
    private const string Ispb = "12345678";
    private readonly IPixRepository _repo;

    public SolicitarDevolucaoHandler(IPixRepository repo) => _repo = repo;

    public async Task<DevolucaoResult> Handle(SolicitarDevolucaoCommand cmd, CancellationToken ct)
    {
        var p = await _repo.ObterPagamento(cmd.PagamentoId, ct);
        if (p is null)
            return new DevolucaoResult(Guid.Empty, "", "ERRO", "Pagamento não encontrado");
        if (p.Status != StatusPagamento.LIQUIDADO)
            return new DevolucaoResult(Guid.Empty, "", "ERRO", $"Pagamento não está LIQUIDADO (está {p.Status})");

        // SLA do MED conforme motivo (golpe = 11d; análise geral = 80d)
        var prazoDias = cmd.Motivo == MotivoDevolucao.FRAUDE ? 11 : 80;

        var dev = new PixDevolucao
        {
            DevolutionId = EndToEndId.GerarDevolucao(Ispb),
            PagamentoId = p.Id, Valor = p.Valor, Motivo = cmd.Motivo,
            Status = StatusDevolucao.BLOQUEADO,   // bloqueio cautelar imediato do recurso
            PrazoLimite = DateTimeOffset.UtcNow.AddDays(prazoDias),
        };
        await _repo.SalvarDevolucao(dev, ct);
        return new DevolucaoResult(dev.Id, dev.DevolutionId, dev.Status.ToString(), null);
    }
}

/// <summary>
/// Resolve a devolução: DEVOLVER (envia pacs.004 ao SPI + estorna movimentos) ou
/// LIBERAR (libera o bloqueio cautelar, sem devolução) ou NEGAR.
/// </summary>
public sealed record ResolverDevolucaoCommand(
    Guid DevolucaoId, StatusDevolucao Resolucao) : IRequest<DevolucaoResult>;

public sealed class ResolverDevolucaoHandler : IRequestHandler<ResolverDevolucaoCommand, DevolucaoResult>
{
    private const string Ispb = "12345678";
    private readonly IPixRepository _repo;
    private readonly ISpiClient _spi;

    public ResolverDevolucaoHandler(IPixRepository repo, ISpiClient spi)
    {
        _repo = repo;
        _spi = spi;
    }

    public async Task<DevolucaoResult> Handle(ResolverDevolucaoCommand cmd, CancellationToken ct)
    {
        var dev = await _repo.ObterDevolucao(cmd.DevolucaoId, ct);
        if (dev is null)
            return new DevolucaoResult(Guid.Empty, "", "ERRO", "Devolução não encontrada");
        if (dev.Status is not (StatusDevolucao.BLOQUEADO or StatusDevolucao.SOLICITADA))
            return new DevolucaoResult(dev.Id, dev.DevolutionId, "ERRO", $"Devolução já resolvida ({dev.Status})");

        var pagamento = await _repo.ObterPagamento(dev.PagamentoId, ct);

        if (cmd.Resolucao == StatusDevolucao.DEVOLVIDO && pagamento is not null)
        {
            // Reason code MD06 = devolução solicitada pelo pagador (fraude/golpe)
            var reason = dev.Motivo == MotivoDevolucao.FRAUDE ? "MD06" : "BE08";
            var pacs004 = Pacs008Builder.BuildPacs004(
                "R" + Guid.NewGuid().ToString("N")[..20], dev.DevolutionId, pagamento.E2eId,
                dev.Valor, reason, pagamento.IspbDestino ?? Ispb, Ispb, DateTimeOffset.UtcNow);

            var ok = await _spi.EnviarPacs004(pacs004, ct);
            dev.Pacs004Xml = pacs004;
            if (ok)
            {
                // Estorna: credita origem, debita destino
                await _repo.EstornarMovimentos(pagamento.CpfOrigem, pagamento.CpfDestino, dev.Valor, pagamento.E2eId, ct);
                dev.Status = StatusDevolucao.DEVOLVIDO;
                pagamento.Status = StatusPagamento.DEVOLVIDO;
                await _repo.AtualizarPagamento(pagamento, ct);
            }
            else
            {
                dev.Status = StatusDevolucao.NEGADO;
            }
        }
        else
        {
            dev.Status = cmd.Resolucao;  // LIBERADO ou NEGADO
        }

        dev.ResolvidoEm = DateTimeOffset.UtcNow;
        await _repo.AtualizarDevolucao(dev, ct);
        return new DevolucaoResult(dev.Id, dev.DevolutionId, dev.Status.ToString(), null);
    }
}
