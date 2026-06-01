using System.ComponentModel.DataAnnotations;
using BankMore.Pix.Application;
using BankMore.Pix.Domain;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BankMore.Pix.Api.Controllers;

[ApiController]
[Route("api/pix")]
public class PixController : ControllerBase
{
    private readonly IMediator _mediator;
    private readonly IPixRepository _repo;

    public PixController(IMediator mediator, IPixRepository repo)
    {
        _mediator = mediator;
        _repo = repo;
    }

    private string? Cpf => User.FindFirst("cpf")?.Value;
    private string Correlation => HttpContext.TraceIdentifier;

    // ------------------------------------------------------------------ Chaves
    [Authorize, HttpPost("chaves")]
    public async Task<IActionResult> RegistrarChave([FromBody] RegistrarChaveRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new RegistrarChaveCommand(Cpf, req.Tipo, req.ValorChave ?? ""), ct);
        return r.Sucesso ? Ok(new { chaveId = r.ChaveId }) : BadRequest(new { erro = r.Erro });
    }

    [Authorize, HttpGet("chaves")]
    public async Task<IActionResult> ListarChaves(CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var idConta = await _repo.ObterIdContaPorCpf(Cpf, ct);
        if (idConta is null) return NotFound();
        var chaves = await _repo.ListarChavesPorConta(idConta, ct);
        return Ok(chaves.Select(c => new { c.ValorChave, tipo = c.Tipo.ToString(), c.Status }));
    }

    // --------------------------------------------------------------- Pagamento
    [Authorize, HttpPost("pagar")]
    public async Task<IActionResult> Pagar([FromBody] PagarRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new IniciarPagamentoCommand(Cpf, req.ChaveDestino, req.Valor, Correlation), ct);
        return ResultadoToHttp(r);
    }

    [Authorize, HttpGet("pagamentos/{id:guid}")]
    public async Task<IActionResult> ObterPagamento(Guid id, CancellationToken ct)
    {
        var p = await _repo.ObterPagamento(id, ct);
        if (p is null) return NotFound();
        return Ok(new
        {
            p.Id, p.E2eId, status = p.Status.ToString(), p.Valor, p.CpfDestino,
            tipoIniciacao = p.TipoIniciacao.ToString(), p.MotivoRejeicao, p.IniciadoEm, p.LiquidadoEm
        });
    }

    // -------------------------------------------------------------- QR Code
    [Authorize, HttpPost("qrcode/estatico")]
    public async Task<IActionResult> QrEstatico([FromBody] QrEstaticoRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new GerarQrEstaticoCommand(Cpf, req.Chave, req.Valor, req.Descricao), ct);
        return Ok(r);
    }

    [Authorize, HttpPost("qrcode/dinamico")]
    public async Task<IActionResult> QrDinamico([FromBody] QrDinamicoRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new GerarQrDinamicoCommand(Cpf, req.Chave, req.Valor, req.Descricao, req.Vencimento), ct);
        return Ok(r);
    }

    [Authorize, HttpPost("qrcode/pagar")]
    public async Task<IActionResult> PagarQr([FromBody] PagarQrRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new PagarQrCodeCommand(Cpf, req.Txid, req.ValorInformado, Correlation), ct);
        return ResultadoToHttp(r);
    }

    // -------------------------------------------------------------- MED
    [Authorize, HttpPost("med")]
    public async Task<IActionResult> SolicitarDevolucao([FromBody] DevolucaoRequest req, CancellationToken ct)
    {
        var r = await _mediator.Send(new SolicitarDevolucaoCommand(req.PagamentoId, req.Motivo), ct);
        return r.Erro is null ? Ok(r) : BadRequest(new { erro = r.Erro });
    }

    [Authorize, HttpPost("med/{id:guid}/resolver")]
    public async Task<IActionResult> ResolverDevolucao(Guid id, [FromBody] ResolverDevolucaoRequest req, CancellationToken ct)
    {
        var r = await _mediator.Send(new ResolverDevolucaoCommand(id, req.Resolucao), ct);
        return r.Erro is null ? Ok(r) : BadRequest(new { erro = r.Erro });
    }

    // -------------------------------------------------- Consentimento (Automático/OF)
    [Authorize, HttpPost("consentimentos")]
    public async Task<IActionResult> CriarConsentimento([FromBody] ConsentimentoRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new CriarConsentimentoCommand(
            req.Tipo, Cpf, req.ChaveRecebedor, req.ValorFixo, req.ValorMaximo,
            req.Periodicidade, req.DataInicio, req.DataFim, req.IdTerceiro), ct);
        return Ok(r);
    }

    [Authorize, HttpPost("consentimentos/{id:guid}/autorizar")]
    public async Task<IActionResult> AutorizarConsentimento(Guid id, CancellationToken ct)
    {
        var r = await _mediator.Send(new AutorizarConsentimentoCommand(id), ct);
        return Ok(r);
    }

    [Authorize, HttpPost("consentimentos/{id:guid}/cobrar")]
    public async Task<IActionResult> CobrarConsentimento(Guid id, CancellationToken ct)
    {
        var r = await _mediator.Send(new ExecutarCobrancaConsentimentoCommand(id), ct);
        return ResultadoToHttp(r);
    }

    // -------------------------------------------------------------- NFC
    [Authorize, HttpPost("nfc/token")]
    public async Task<IActionResult> GerarNfcToken([FromBody] NfcTokenRequest req, CancellationToken ct)
    {
        if (Cpf is null) return Unauthorized();
        var r = await _mediator.Send(new GerarNfcTokenCommand(Cpf, req.ValorMaximo, req.TtlSegundos), ct);
        return r is null ? NotFound(new { erro = "Conta não encontrada" }) : Ok(r);
    }

    [Authorize, HttpPost("nfc/pagar")]
    public async Task<IActionResult> PagarNfc([FromBody] PagarNfcRequest req, CancellationToken ct)
    {
        var r = await _mediator.Send(new PagarNfcCommand(req.Token, req.ChaveRecebedor, req.Valor, Correlation), ct);
        return ResultadoToHttp(r);
    }

    // -------------------------------------------------------------- helpers
    private IActionResult ResultadoToHttp(ResultadoPagamento r) => r.Status switch
    {
        "LIQUIDADO" => Ok(r),
        "REJEITADO" => UnprocessableEntity(r),
        _ => Accepted(r),
    };
}

// ----------------------------- DTOs -----------------------------
public sealed record RegistrarChaveRequest([Required] TipoChave Tipo, string? ValorChave);
public sealed record PagarRequest([Required] string ChaveDestino, [Range(0.01, 9999999)] decimal Valor);
public sealed record QrEstaticoRequest([Required] string Chave, decimal? Valor, string? Descricao);
public sealed record QrDinamicoRequest([Required] string Chave, [Range(0.01, 9999999)] decimal Valor, string? Descricao, DateTimeOffset? Vencimento);
public sealed record PagarQrRequest([Required] string Txid, decimal? ValorInformado);
public sealed record DevolucaoRequest([Required] Guid PagamentoId, [Required] MotivoDevolucao Motivo);
public sealed record ResolverDevolucaoRequest([Required] StatusDevolucao Resolucao);
public sealed record ConsentimentoRequest(
    [Required] TipoConsentimento Tipo, [Required] string ChaveRecebedor,
    decimal? ValorFixo, decimal? ValorMaximo, string? Periodicidade,
    DateOnly? DataInicio, DateOnly? DataFim, string? IdTerceiro);
public sealed record NfcTokenRequest([Range(0.01, 9999999)] decimal ValorMaximo, int TtlSegundos = 60);
public sealed record PagarNfcRequest([Required] string Token, [Required] string ChaveRecebedor, [Range(0.01, 9999999)] decimal Valor);
