using BankMore.BacenSim.Dict;
using BankMore.BacenSim.Iso20022;
using BankMore.BacenSim.Spi;
using Microsoft.AspNetCore.Mvc;
using Prometheus;

// ============================================================================
// BankMore bacen-sim — simulador do BACEN (DICT + SPI) — Sprint 8.A
//
// NÃO é o BACEN real. Conectar no SPI de verdade exige ISPB homologado,
// certificado ICP-Brasil (mTLS na RSFN) e processo de homologação. Este serviço
// simula o lado do BACEN pra demonstrar a interconexão de pagamentos instantâneos:
// resolução de chave no DICT + liquidação ISO 20022 com SLA <10s.
// ============================================================================

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("ASPNETCORE_URLS") ?? "http://+:8080");

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddSingleton<DictStore>();
builder.Services.AddSingleton<SpiSettler>();

var app = builder.Build();
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
