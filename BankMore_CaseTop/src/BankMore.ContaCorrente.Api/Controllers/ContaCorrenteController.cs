using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Application.Models;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BankMore.ContaCorrente.Api.Controllers
{
    [ApiController]
    [Authorize]                       // Exige JWT em TODO endpoint da classe — exceto os marcados.
    [Route("api/[controller]")]
    public class ContaCorrenteController(IMediator mediator) : ControllerBase
    {
        // Sem try/catch: ExceptionMiddleware global mapeia ArgumentException → 400,
        // InvalidOperationException → 409, etc. Controller fica focado em orquestrar.

        [HttpPost("criar")]
        [AllowAnonymous]
        public async Task<IActionResult> Cadastrar([FromBody] CadastrarContaCommand command)
            => Ok(await mediator.Send(command));

        [HttpPost("login")]
        [AllowAnonymous]
        public async Task<IActionResult> Login([FromBody] LoginCommand command)
        {
            var resultado = await mediator.Send(command);
            return resultado is { Autenticado: true }
                ? Ok(resultado)
                : Unauthorized(new { mensagem = resultado?.Mensagem ?? "Falha na autenticação" });
        }

        /// <summary>Saldo do usuário autenticado (CPF vem do JWT, NÃO da URL).</summary>
        [HttpGet("saldo")]
        public async Task<IActionResult> ObterSaldo()
            => Ok(await mediator.Send(new ObterSaldoQuery(CpfDoToken())));

        /// <summary>Extrato do usuário autenticado (CPF vem do JWT).</summary>
        [HttpGet("extrato")]
        public async Task<IActionResult> ObterExtrato()
            => Ok(await mediator.Send(new ObterExtratoQuery(CpfDoToken())) ?? new ObterExtratoResponse());

        /// <summary>
        /// Movimentação direta (depósito/saque) — não confundir com Transferência.
        /// Sempre afeta a conta do usuário autenticado.
        /// </summary>
        [HttpPost("movimentar")]
        public async Task<IActionResult> Movimentar([FromBody] MovimentarRequest request)
        {
            await mediator.Send(new EfetuarMovimentacaoCommand(
                request.RequestId ?? Guid.NewGuid().ToString(),
                CpfDoToken(),
                request.Valor,
                request.Tipo));
            return NoContent();
        }

        private string CpfDoToken()
        {
            var cpf = User.FindFirst("cpf")?.Value;
            return string.IsNullOrEmpty(cpf)
                ? throw new UnauthorizedAccessException("Token sem claim 'cpf'")
                : cpf;
        }
    }

    public record MovimentarRequest(decimal Valor, string Tipo, string? RequestId);
}
