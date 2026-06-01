using System.Security.Cryptography.X509Certificates;
using BankMore.BacenSim.Dict;
using BankMore.BacenSim.Iso20022;
using BankMore.BacenSim.Spi;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Server.Kestrel.Https;
using Prometheus;

// ============================================================================
// BankMore bacen-sim — simulador do BACEN (DICT + SPI) — Sprint 8.A / mTLS 10.B
//
// NÃO é o BACEN real. Conectar no SPI de verdade exige ISPB homologado,
// certificado ICP-Brasil (mTLS na RSFN) e processo de homologação. Este serviço
// simula o lado do BACEN pra demonstrar a interconexão de pagamentos instantâneos:
// resolução de chave no DICT + liquidação ISO 20022 com SLA <10s.
//
// Sprint 10.B — mTLS: com MTLS_ENABLED=true, os endpoints DICT/SPI passam a exigir
// um client certificate emitido pela CA (papel da AC Raiz ICP-Brasil), espelhando
// a RSFN. HTTP 8080 segue aberto só pra health/metrics/swagger (management).
// ============================================================================

var builder = WebApplication.CreateBuilder(args);

var mtlsEnabled = (Environment.GetEnvironmentVariable("MTLS_ENABLED") ?? "false") == "true";
if (mtlsEnabled)
{
    var serverPfx = Environment.GetEnvironmentVariable("MTLS_SERVER_PFX") ?? "/certs/server.pfx";
    var pfxPass = Environment.GetEnvironmentVariable("MTLS_PFX_PASS") ?? "bankmore";
    var caPath = Environment.GetEnvironmentVariable("MTLS_CA_CRT") ?? "/certs/ca.crt";
    var serverCert = new X509Certificate2(serverPfx, pfxPass);
    var caCert = new X509Certificate2(caPath);

    builder.WebHost.ConfigureKestrel(opts =>
    {
        // 8080 HTTP — management (health/metrics/swagger), sem mTLS
        opts.ListenAnyIP(8080);
        // 8443 HTTPS — DICT/SPI com mTLS (client cert obrigatório, validado contra a CA)
        opts.ListenAnyIP(8443, lo => lo.UseHttps(serverCert, https =>
        {
            https.ClientCertificateMode = ClientCertificateMode.RequireCertificate;
            https.ClientCertificateValidation = (cert, _, _) => ValidaContraCa(cert, caCert);
        }));
    });
}
else
{
    builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("ASPNETCORE_URLS") ?? "http://+:8080");
}

// Valida que o client cert foi emitido pela nossa CA (cadeia confiável customizada).
// É o que o BACEN faz na RSFN: só aceita PSPs com cert da cadeia ICP-Brasil.
static bool ValidaContraCa(X509Certificate2 clientCert, X509Certificate2 caCert)
{
    using var chain = new X509Chain();
    chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
    chain.ChainPolicy.CustomTrustStore.Add(caCert);
    chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
    return chain.Build(clientCert);
}

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddSingleton<DictStore>();
builder.Services.AddSingleton<SpiSettler>();

var app = builder.Build();

// Sprint 10.B — quando mTLS está ligado, DICT/SPI só respondem com client cert
// presente (handshake mTLS na 8443). Bloqueia tentativa de acesso via HTTP 8080,
// que existe apenas pra management (health/metrics/swagger).
if (mtlsEnabled)
{
    app.Use(async (ctx, next) =>
    {
        var path = ctx.Request.Path.Value ?? "";
        if ((path.StartsWith("/dict") || path.StartsWith("/spi")) && ctx.Connection.ClientCertificate is null)
        {
            ctx.Response.StatusCode = StatusCodes.Status403Forbidden;
            await ctx.Response.WriteAsJsonAsync(new
            {
                erro = "mTLS obrigatório: client certificate ausente. A RSFN exige certificado da cadeia ICP-Brasil."
            });
            return;
        }
        await next();
    });
}

app.UseSwagger();
app.UseSwaggerUI();
app.UseHttpMetrics();
app.MapMetrics("/metrics");

var dictResolucoes = Metrics.CreateCounter("bacensim_dict_resolucoes_total", "Resoluções DICT", "resultado");
var spiLiquidacoes = Metrics.CreateCounter("bacensim_spi_liquidacoes_total", "Liquidações SPI", "status");

app.MapGet("/health", () => Results.Ok(new { status = "UP", servico = "bacen-sim" }));

// ----------------------------------------------------------------------------
// DICT — Diretório de Identificadores de Contas Transacionais
// ----------------------------------------------------------------------------
app.MapGet("/dict/entries/{chave}", (string chave, DictStore dict) =>
{
    var e = dict.Resolver(chave);
    if (e is null)
    {
        dictResolucoes.WithLabels("nao_encontrada").Inc();
        return Results.NotFound(new { erro = "Chave não encontrada no DICT", chave });
    }
    dictResolucoes.WithLabels("encontrada").Inc();
    // CPF mascarado como o DICT real retorna (***.456.789-**)
    return Results.Ok(new
    {
        chave = e.Chave,
        tipo = e.Tipo,
        ispb = e.Ispb,
        cpfMascarado = MascararCpf(e.CpfTitular),
        cpfTitular = e.CpfTitular,   // demo: retornamos cheio p/ liquidação intra-PSP
        nomeTitular = e.NomeTitular,
        status = e.Status,
    });
});

app.MapPost("/dict/entries", ([FromBody] RegistrarChaveReq req, DictStore dict) =>
{
    if (string.IsNullOrWhiteSpace(req.Chave) || string.IsNullOrWhiteSpace(req.CpfTitular))
        return Results.BadRequest(new { erro = "chave e cpfTitular obrigatórios" });

    var e = dict.Registrar(req.Chave, req.Tipo ?? "EVP",
        req.Ispb ?? "12345678", req.CpfTitular, req.NomeTitular ?? "");
    return Results.Created($"/dict/entries/{e.Chave}", new { chave = e.Chave, status = e.Status });
});

app.MapDelete("/dict/entries/{chave}", (string chave, [FromQuery] string cpfTitular, DictStore dict) =>
    dict.Remover(chave, cpfTitular)
        ? Results.NoContent()
        : Results.NotFound(new { erro = "Chave não encontrada ou titular não confere" }));

app.MapPost("/dict/entries/{chave}/claims", (string chave, [FromBody] ClaimReq req, DictStore dict) =>
{
    var claim = dict.AbrirClaim(chave, req.TipoClaim ?? "PORTABILIDADE",
        req.IspbReivindicador ?? "12345678", req.CpfReivindicador, req.NomeReivindicador ?? "");
    return Results.Ok(new { claimId = claim.Id, status = claim.Status, chave });
});

app.MapGet("/dict/entries", (DictStore dict) =>
    Results.Ok(dict.Listar().Select(e => new { e.Chave, e.Tipo, e.Ispb, e.CpfTitular, e.Status })));

// ----------------------------------------------------------------------------
// SPI — liquidação ISO 20022
// ----------------------------------------------------------------------------
app.MapPost("/spi/pacs008", async (HttpRequest httpReq, SpiSettler spi, CancellationToken ct) =>
{
    using var reader = new StreamReader(httpReq.Body);
    var pacs008 = await reader.ReadToEndAsync(ct);

    var result = await spi.LiquidarAsync(pacs008, ct);
    spiLiquidacoes.WithLabels(result.Status).Inc();

    // Responde pacs.002 como application/xml (igual SPI real)
    return Results.Content(result.Pacs002Xml, "application/xml");
});

app.MapPost("/spi/pacs004", async (HttpRequest httpReq, ILogger<Program> log, CancellationToken ct) =>
{
    using var reader = new StreamReader(httpReq.Body);
    var pacs004 = await reader.ReadToEndAsync(ct);
    log.LogInformation("SPI recebeu devolução pacs.004 ({Len} bytes)", pacs004.Length);

    // Liquidação da devolução: SPI aceita e move o valor de volta. Responde ACSC.
    await Task.Delay(Random.Shared.Next(50, 300), ct);
    var pacs002 = Iso20022Messages.BuildPacs002(
        "SPI" + Guid.NewGuid().ToString("N")[..20], "RTR", "DEVOLUCAO", "ACSC", null, DateTimeOffset.UtcNow);
    spiLiquidacoes.WithLabels("ACSC_DEVOLUCAO").Inc();
    return Results.Content(pacs002, "application/xml");
});

app.Run();

static string MascararCpf(string cpf) =>
    cpf.Length == 11 ? $"***.{cpf.Substring(3, 3)}.{cpf.Substring(6, 3)}-**" : "***";

record RegistrarChaveReq(string Chave, string? Tipo, string? Ispb, string CpfTitular, string? NomeTitular);
record ClaimReq(string? TipoClaim, string? IspbReivindicador, string CpfReivindicador, string? NomeReivindicador);
