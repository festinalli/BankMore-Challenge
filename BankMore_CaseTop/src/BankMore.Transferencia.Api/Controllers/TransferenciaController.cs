using BankMore.Transferencia.Application.Handlers;
using BankMore.Transferencia.Domain.Enums;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.ComponentModel.DataAnnotations;

namespace BankMore.Transferencia.Api.Controllers
{
    [Route("api/[controller]")]
    [ApiController]
    [Authorize]
    public class TransferenciaController(IMediator mediator) : ControllerBase
    {
        [HttpPost("efetuar")]
        public async Task<IActionResult> Transferir([FromBody] TransferenciaRequest request)
        {
            // CPF de origem vem do JWT — cliente NÃO pode escolher conta alheia
            var cpfOrigem = User.FindFirst("cpf")?.Value;
            if (string.IsNullOrEmpty(cpfOrigem))
                return Unauthorized(new { mensagem = "Token sem claim 'cpf'" });

            if (request.Valor <= 0)
                return BadRequest(new { mensagem = "Valor deve ser positivo" });

            if (request.CpfDestino == cpfOrigem)
                return BadRequest(new { mensagem = "Auto-transferência não permitida" });

            var correlationId = HttpContext.TraceIdentifier;

            var command = new EfetuarTransferenciaCommand(
                cpfOrigem,
                request.CpfDestino,
                request.Valor,
                request.Tipo,
                correlationId
            );

            var result = await mediator.Send(command);

            return Accepted(new
            {
                id = result.Id,
                correlationId = result.CorrelationId,
                status = result.Status,
                tipo = request.Tipo.ToString(),
                mensagem = "Transferência aceita; análise de fraude em andamento"
            });
        }
    }

    public record TransferenciaRequest(
        [Required, StringLength(11, MinimumLength = 11)] string CpfDestino,
        [Range(0.01, 1_000_000)] decimal Valor,
        TipoTransferencia Tipo
    );
}
