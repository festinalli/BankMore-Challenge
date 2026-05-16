using System.Text.Json;

namespace BankMore.ContaCorrente.Api.Middleware;

/// <summary>
/// Middleware global de tratamento de exceções de domínio.
///
/// Mapeia exceções tipadas → status HTTP semântico, devolvendo JSON
/// estável { mensagem, codigo, correlationId } pro client. Remove a
/// necessidade de try/catch repetitivo nos controllers — eles ficam
/// no que importa (orquestrar handler MediatR e devolver resultado).
///
/// Mapeamento:
///   ArgumentException           → 400 Bad Request
///   InvalidOperationException   → 409 Conflict (já existe, estado inválido)
///   UnauthorizedAccessException → 401 Unauthorized
///   KeyNotFoundException        → 404 Not Found
///   Outras                      → 500 + log estruturado
///
/// CorrelationId vem do TraceIdentifier do request — útil pra correlacionar
/// nos logs (`grep` por correlationId).
/// </summary>
public class ExceptionMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<ExceptionMiddleware> _logger;

    public ExceptionMiddleware(RequestDelegate next, ILogger<ExceptionMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (ArgumentException ex)
        {
            await Respond(context, StatusCodes.Status400BadRequest, ex.Message, "VALIDACAO");
        }
        catch (InvalidOperationException ex)
        {
            await Respond(context, StatusCodes.Status409Conflict, ex.Message, "ESTADO_INVALIDO");
        }
        catch (UnauthorizedAccessException ex)
        {
            await Respond(context, StatusCodes.Status401Unauthorized, ex.Message, "NAO_AUTORIZADO");
        }
        catch (KeyNotFoundException ex)
        {
            await Respond(context, StatusCodes.Status404NotFound, ex.Message, "NAO_ENCONTRADO");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Erro inesperado em {Path} (correlationId={CorrelationId})",
                context.Request.Path, context.TraceIdentifier);
            await Respond(context, StatusCodes.Status500InternalServerError,
                "Erro inesperado. Tente novamente.", "ERRO_INTERNO");
        }
    }

    private static async Task Respond(HttpContext ctx, int status, string mensagem, string codigo)
    {
        if (ctx.Response.HasStarted) return;
        ctx.Response.Clear();
        ctx.Response.StatusCode = status;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        var payload = JsonSerializer.Serialize(new
        {
            mensagem,
            codigo,
            correlationId = ctx.TraceIdentifier
        });
        await ctx.Response.WriteAsync(payload);
    }
}
