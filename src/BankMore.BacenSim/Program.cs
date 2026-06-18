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

// Manual Pix v6.0 §5.1 — assinatura de mensagem (CERTPIA). O regulador verifica a
// assinatura da pacs.008/004 recebida do PSP e assina a pacs.002 de resposta, com um
// cert de finalidade DISTINTA do cert de canal mTLS (server.pfx/CERTPIC).
var pixSignEnabled = (Environment.GetEnvironmentVariable("PIX_SIGN_ENABLED") ?? "false") == "true";
X509Certificate2? certPiaSim = null;
X509Certificate2? caAssinatura = null;
if (pixSignEnabled)
{
    var signPfx = Environment.GetEnvironmentVariable("MTLS_SIGN_PFX") ?? "/certs/sign-bacen-sim.pfx";
    var signPass = Environment.GetEnvironmentVariable("MTLS_PFX_PASS") ?? "bankmore";
    var caPath = Environment.GetEnvironmentVariable("MTLS_CA_CRT") ?? "/certs/ca.crt";
    certPiaSim = new X509Certificate2(signPfx, signPass);
    caAssinatura = new X509Certificate2(caPath);
}
var pacsAssinatura = new PacsAssinatura(certPiaSim, caAssinatura);

// Manual Pix v6.0 §2.1 — controle de origem de acesso à ICOM via IP allowlist.
// Só IPs/faixas explicitamente autorizados (CIDRs em ICOM_IP_ALLOWLIST) podem
// estabelecer conexão com o DICT/SPI da RSFN. Defesa em camadas: roda ANTES do gate
// mTLS. Em produção a lista é provisionada pelo BACEN sobre os IPs do ISPB homologado;
// aqui representa o segmento de rede dedicado da RSFN simulada.
var icomAllowlistEnabled = (Environment.GetEnvironmentVariable("ICOM_IP_ALLOWLIST_ENABLED") ?? "false") == "true";
var icomAllowlist = new List<System.Net.IPNetwork>();
foreach (var cidr in (Environment.GetEnvironmentVariable("ICOM_IP_ALLOWLIST") ?? "")
    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
{
    if (System.Net.IPNetwork.TryParse(cidr, out var net)) icomAllowlist.Add(net);
}

var app = builder.Build();

// §2.1 — métrica de acesso à ICOM (permitido / negado por IP / negado por cert).
var icomAcessos = Metrics.CreateCounter("bacensim_icom_acessos_total",
    "Tentativas de acesso à ICOM (DICT/SPI) por resultado (Manual Pix v6.0 §2.1)", "resultado");

// §2.1 — IP allowlist: rejeita origens não autorizadas ANTES do gate mTLS (camada 1).
if (mtlsEnabled && icomAllowlistEnabled)
{
    app.Use(async (ctx, next) =>
    {
        var path = ctx.Request.Path.Value ?? "";
        if (path.StartsWith("/dict") || path.StartsWith("/spi"))
        {
            var ip = ctx.Connection.RemoteIpAddress;
            if (ip is not null && ip.IsIPv4MappedToIPv6) ip = ip.MapToIPv4(); // docker entrega IPv4-mapeado
            var permitido = ip is not null && icomAllowlist.Any(n => n.Contains(ip));
            if (!permitido)
            {
                icomAcessos.WithLabels("negado_ip").Inc();
                app.Logger.LogWarning("ICOM acesso NEGADO por origem não autorizada: ip={Ip} path={Path}", ip, path);
                ctx.Response.StatusCode = StatusCodes.Status403Forbidden;
                await ctx.Response.WriteAsJsonAsync(new { erro = "Origem não autorizada na ICOM (IP allowlist da RSFN)" });
                return;
            }
        }
        await next();
    });
}

// Sprint 10.B + §2.1 — gate mTLS (camada 2): DICT/SPI só com client cert presente
// (handshake na 8443). Bloqueia acesso via HTTP 8080 (management). Audita a origem de
// CADA tentativa (IP + CN/thumbprint do cert + resultado) — trilha exigida pelo §2.1.
if (mtlsEnabled)
{
    app.Use(async (ctx, next) =>
    {
        var path = ctx.Request.Path.Value ?? "";
        if (path.StartsWith("/dict") || path.StartsWith("/spi"))
        {
            var ip = ctx.Connection.RemoteIpAddress;
            var cert = ctx.Connection.ClientCertificate;
            if (cert is null)
            {
                icomAcessos.WithLabels("negado_cert").Inc();
                app.Logger.LogWarning("ICOM acesso NEGADO sem client cert: ip={Ip} path={Path}", ip, path);
                ctx.Response.StatusCode = StatusCodes.Status403Forbidden;
                await ctx.Response.WriteAsJsonAsync(new
                {
                    erro = "mTLS obrigatório: client certificate ausente. A RSFN exige certificado da cadeia ICP-Brasil."
                });
                return;
            }
            icomAcessos.WithLabels("permitido").Inc();
            app.Logger.LogInformation("ICOM acesso PERMITIDO: ip={Ip} cn={Cn} thumbprint={Thumb} path={Path}",
                ip, cert.GetNameInfo(X509NameType.SimpleName, false), cert.Thumbprint, path);
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
var spiAssinatura = Metrics.CreateCounter("bacensim_spi_assinatura_total",
    "Verificações de assinatura de mensagem CERTPIA (Manual Pix v6.0 §5.1)", "resultado");

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

    // §5.1 — exige assinatura CERTPIA válida do PSP ANTES de liquidar. Sem assinatura
    // (ou inválida/cert de canal), rejeita com RJCT e responde pacs.002 assinada.
    if (pixSignEnabled && !pacsAssinatura.Verificar(pacs008))
    {
        spiAssinatura.WithLabels("pacs008_invalida").Inc();
        spiLiquidacoes.WithLabels("RJCT_ASSINATURA").Inc();
        var rjct = Iso20022Messages.BuildPacs002(
            "SPI" + Guid.NewGuid().ToString("N")[..20], "", "", "RJCT", "FF01", DateTimeOffset.UtcNow);
        return Results.Content(pacsAssinatura.Assinar(rjct), "application/xml");
    }
    if (pixSignEnabled) spiAssinatura.WithLabels("pacs008_valida").Inc();

    var result = await spi.LiquidarAsync(pacs008, ct);
    spiLiquidacoes.WithLabels(result.Status).Inc();

    // Responde pacs.002 como application/xml (igual SPI real), assinada com o CERTPIA do SPI.
    var resposta = pixSignEnabled ? pacsAssinatura.Assinar(result.Pacs002Xml) : result.Pacs002Xml;
    return Results.Content(resposta, "application/xml");
});

app.MapPost("/spi/pacs004", async (HttpRequest httpReq, ILogger<Program> log, CancellationToken ct) =>
{
    using var reader = new StreamReader(httpReq.Body);
    var pacs004 = await reader.ReadToEndAsync(ct);
    log.LogInformation("SPI recebeu devolução pacs.004 ({Len} bytes)", pacs004.Length);

    // §5.1 — a devolução também exige assinatura CERTPIA válida do PSP.
    if (pixSignEnabled && !pacsAssinatura.Verificar(pacs004))
    {
        spiAssinatura.WithLabels("pacs004_invalida").Inc();
        var rjct = Iso20022Messages.BuildPacs002(
            "SPI" + Guid.NewGuid().ToString("N")[..20], "RTR", "DEVOLUCAO", "RJCT", "FF01", DateTimeOffset.UtcNow);
        return Results.Content(pacsAssinatura.Assinar(rjct), "application/xml");
    }
    if (pixSignEnabled) spiAssinatura.WithLabels("pacs004_valida").Inc();

    // Liquidação da devolução: SPI aceita e move o valor de volta. Responde ACSC.
    await Task.Delay(Random.Shared.Next(50, 300), ct);
    var pacs002 = Iso20022Messages.BuildPacs002(
        "SPI" + Guid.NewGuid().ToString("N")[..20], "RTR", "DEVOLUCAO", "ACSC", null, DateTimeOffset.UtcNow);
    spiLiquidacoes.WithLabels("ACSC_DEVOLUCAO").Inc();
    var resposta = pixSignEnabled ? pacsAssinatura.Assinar(pacs002) : pacs002;
    return Results.Content(resposta, "application/xml");
});

app.Run();

static string MascararCpf(string cpf) =>
    cpf.Length == 11 ? $"***.{cpf.Substring(3, 3)}.{cpf.Substring(6, 3)}-**" : "***";

record RegistrarChaveReq(string Chave, string? Tipo, string? Ispb, string CpfTitular, string? NomeTitular);
record ClaimReq(string? TipoClaim, string? IspbReivindicador, string CpfReivindicador, string? NomeReivindicador);
