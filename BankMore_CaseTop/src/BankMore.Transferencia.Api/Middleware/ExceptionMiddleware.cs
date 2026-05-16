using System.Text.Json;

namespace BankMore.Transferencia.Api.Middleware;

/// <summary>Mesmo padrão da ContaCorrente.Api — exceções de domínio → status HTTP semântico.</summary>
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
        try { await _next(context); }
        catch (ArgumentException ex) { await Respond(context, 400, ex.Message, "VALIDACAO"); }
        catch (InvalidOperationException ex) { await Respond(context, 409, ex.Message, "ESTADO_INVALIDO"); }
        catch (UnauthorizedAccessException ex) { await Respond(context, 401, ex.Message, "NAO_AUTORIZADO"); }
        catch (KeyNotFoundException ex) { await Respond(context, 404, ex.Message, "NAO_ENCONTRADO"); }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Erro inesperado em {Path} (correlationId={CorrelationId})",
                context.Request.Path, context.TraceIdentifier);
            await Respond(context, 500, "Erro inesperado. Tente novamente.", "ERRO_INTERNO");
        }
    }

    private static async Task Respond(HttpContext ctx, int status, string mensagem, string codigo)
    {
        if (ctx.Response.HasStarted) return;
        ctx.Response.Clear();
        ctx.Response.StatusCode = status;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        await ctx.Response.WriteAsync(JsonSerializer.Serialize(new
        {
            mensagem, codigo, correlationId = ctx.TraceIdentifier
        }));
    }
}
