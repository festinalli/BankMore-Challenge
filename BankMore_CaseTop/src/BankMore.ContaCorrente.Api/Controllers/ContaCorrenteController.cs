using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Application.Models;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BankMore.ContaCorrente.Api.Controllers
{
    [ApiController]
    [Authorize]                       // <- exige JWT em TODO endpoint da classe...
    [Route("api/[controller]")]
    public class ContaCorrenteController(IMediator mediator, ILogger<ContaCorrenteController> logger) : ControllerBase
    {
        [HttpPost("criar")]
        [AllowAnonymous]              // ...exceto cadastro
        public async Task<IActionResult> Cadastrar([FromBody] CadastrarContaCommand command)
        {
            try
            {
                var resultado = await mediator.Send(command);
                return Ok(resultado);
            }
            catch (ArgumentException ex)
            {
                return BadRequest(new { mensagem = ex.Message });
            }
            catch (InvalidOperationException ex)
            {
                return Conflict(new { mensagem = ex.Message });
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Erro inesperado ao cadastrar conta");
                return StatusCode(500, new { mensagem = "Erro inesperado ao cadastrar a conta" });
            }
        }

        [HttpPost("login")]
        [AllowAnonymous]              // ...e login
        public async Task<IActionResult> Login([FromBody] LoginCommand command)
        {
            var resultado = await mediator.Send(command);

            if (resultado is null || !resultado.Autenticado)
                return Unauthorized(new { mensagem = resultado?.Mensagem ?? "Falha na autenticação" });

            return Ok(resultado);
        }

        /// <summary>Saldo do usuário autenticado (CPF vem do JWT, NÃO da URL).</summary>
        [HttpGet("saldo")]
        public async Task<IActionResult> ObterSaldo()
        {
            var cpf = User.FindFirst("cpf")?.Value;
            if (string.IsNullOrEmpty(cpf))
                return Unauthorized(new { mensagem = "Token sem claim 'cpf'" });

            var resultado = await mediator.Send(new ObterSaldoQuery(cpf));
            return Ok(resultado);
        }

        /// <summary>Extrato do usuário autenticado (CPF vem do JWT).</summary>
        [HttpGet("extrato")]
        public async Task<IActionResult> ObterExtrato()
        {
            var cpf = User.FindFirst("cpf")?.Value;
            if (string.IsNullOrEmpty(cpf))
                return Unauthorized(new { mensagem = "Token sem claim 'cpf'" });

            var resultado = await mediator.Send(new ObterExtratoQuery(cpf));
            return Ok(resultado ?? new ObterExtratoResponse());
        }

        /// <summary>
        /// Movimentação direta (depósito/saque) — não confundir com Transferência.
        /// Sempre afeta a conta do usuário autenticado.
        /// </summary>
        [HttpPost("movimentar")]
        public async Task<IActionResult> Movimentar([FromBody] MovimentarRequest request)
        {
            var cpf = User.FindFirst("cpf")?.Value;
            if (string.IsNullOrEmpty(cpf))
                return Unauthorized(new { mensagem = "Token sem claim 'cpf'" });

            try
            {
                await mediator.Send(new EfetuarMovimentacaoCommand(
                    request.RequestId ?? Guid.NewGuid().ToString(),
                    cpf,
                    request.Valor,
                    request.Tipo
                ));
                return NoContent();
            }
            catch (ArgumentException ex)
            {
                return BadRequest(new { mensagem = ex.Message });
            }
        }
    }

    public record MovimentarRequest(decimal Valor, string Tipo, string? RequestId);
}
