using BankMore.Transferencia.Api.Middleware;
using BankMore.Transferencia.Domain;
using Microsoft.AspNetCore.Mvc;

namespace BankMore.Transferencia.Api.Controllers;

/// <summary>
/// Endpoints administrativos do outbox/DLQ.
///
/// Sprint 6.A — endpoints sem auth (rede interna do compose).
/// Sprint 7.B — bearer token via [RequireAdminToken]. Sem env Outbox__AdminToken,
/// retorna 503 (fail-closed). Sprint 8 vai migrar pra JWT com role=ops.
/// </summary>
[ApiController]
[Route("api/admin/outbox")]
[RequireAdminToken]
public class OutboxAdminController : ControllerBase
{
    private readonly ITransferenciaRepository _repo;
    private readonly ILogger<OutboxAdminController> _logger;

    public OutboxAdminController(ITransferenciaRepository repo, ILogger<OutboxAdminController> logger)
    {
        _repo = repo;
        _logger = logger;
    }

    /// <summary>Lista mensagens em DLQ (limite default 50).</summary>
    [HttpGet("dlq")]
    public async Task<IActionResult> ListarDlq([FromQuery] int limite = 50, CancellationToken ct = default)
    {
        var items = await _repo.ListarDeadLetter(Math.Clamp(limite, 1, 500), ct);
        return Ok(new
        {
            total = items.Count,
            items = items.Select(i => new
            {
                id = i.Id,
                transferenciaId = i.TransferenciaId,
                topic = i.Topic,
                tentativas = i.Tentativas,
                // payload é truncado em log; retorna inteiro pra debugging
                payload = i.PayloadJson,
            }),
        });
    }

    /// <summary>Replay manual: reseta DLQ → relay pega no próximo poll.</summary>
    [HttpPost("dlq/{id:guid}/reprocess")]
    public async Task<IActionResult> Reprocessar([FromRoute] Guid id, CancellationToken ct)
    {
        var ok = await _repo.ReprocessarDeadLetter(id, ct);
        if (!ok)
            return NotFound(new { erro = "Row não encontrada ou não está em DLQ" });

        _logger.LogInformation("DLQ replay solicitado pelo admin: {Id}", id);
        return Ok(new { mensagem = "Reprocessamento agendado — relay vai pegar no próximo poll" });
    }
}
