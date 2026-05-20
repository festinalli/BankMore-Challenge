using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;

namespace BankMore.Transferencia.Api.Middleware;

/// <summary>
/// Sprint 7.B — Auth simples baseado em shared-secret pros endpoints admin do outbox.
///
/// Por que não JWT: o JWT existente é emitido pelo ContaCorrente.Api e carrega claims
/// de cliente final (sub=cpf). Adicionar role=ops nesse fluxo exigiria endpoint de
/// admin login + tabela de operadores. Pra v1 de demo, um shared-secret em env var
/// é proporcional ao risco (endpoints só são acessíveis pela rede interna do compose
/// e ainda ficam atrás do API gateway numa instalação real). Sprint 8 troca por JWT
/// com role=ops emitido por IdP separado.
///
/// Uso:
///   [RequireAdminToken]
///   public IActionResult Endpoint() { ... }
///
/// Config:
///   Outbox__AdminToken=<segredo>      → header esperado: Authorization: Bearer <segredo>
///   Outbox__AdminToken não definido   → 503 Service Unavailable (fail-closed)
/// </summary>
public sealed class RequireAdminTokenAttribute : Attribute, IAsyncActionFilter
{
    private const string CONFIG_KEY = "Outbox:AdminToken";

    public async Task OnActionExecutionAsync(ActionExecutingContext context, ActionExecutionDelegate next)
    {
        var config = context.HttpContext.RequestServices.GetRequiredService<IConfiguration>();
        var expected = config[CONFIG_KEY];

        // Fail-closed: sem token configurado = endpoint desabilitado.
        // Evita o footgun de subir prod sem env var e expor admin pra todo mundo.
        if (string.IsNullOrWhiteSpace(expected))
        {
            context.Result = new ObjectResult(new { erro = "Endpoint admin desabilitado (Outbox__AdminToken não configurado)" })
            {
                StatusCode = StatusCodes.Status503ServiceUnavailable,
            };
            return;
        }

        var header = context.HttpContext.Request.Headers.Authorization.ToString();
        if (string.IsNullOrEmpty(header) || !header.StartsWith("Bearer ", StringComparison.Ordinal))
        {
            context.Result = new UnauthorizedObjectResult(new { erro = "Authorization: Bearer <token> requerido" });
            return;
        }

        var presented = header.Substring("Bearer ".Length).Trim();

        // Comparação constant-time pra mitigar timing attack (overkill pra demo,
        // mas escrever o caminho certo desde o início ajuda quem for ler o código).
        if (!FixedTimeEquals(presented, expected))
        {
            context.Result = new UnauthorizedObjectResult(new { erro = "Token admin inválido" });
            return;
        }

        await next();
    }

    private static bool FixedTimeEquals(string a, string b)
    {
        if (a.Length != b.Length) return false;
        var diff = 0;
        for (var i = 0; i < a.Length; i++)
            diff |= a[i] ^ b[i];
        return diff == 0;
    }
}
