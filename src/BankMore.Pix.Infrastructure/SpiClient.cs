using System.Text;
using System.Xml.Linq;
using BankMore.Pix.Domain;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// HTTP client do SPI no bacen-sim (envia pacs.008/004, lê pacs.002).
///
/// Manual Pix v6.0 §5.1 — quando a assinatura de mensagem está ativa, assina a
/// pacs.008/pacs.004 com o CERTPIA (cert de assinatura, distinto do cert de canal)
/// antes de enviar, e verifica a assinatura da pacs.002 devolvida pelo regulador.
/// </summary>
public sealed class SpiClient : ISpiClient
{
    private static readonly XNamespace NsPacs002 = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10";
    private readonly HttpClient _http;
    private readonly PacsAssinatura _assinatura;
    private readonly bool _signEnabled;

    public SpiClient(HttpClient http, PacsAssinatura assinatura, PixSignConfig signCfg)
    {
        _http = http;
        _assinatura = assinatura;
        _signEnabled = signCfg.Habilitado;
    }

    public async Task<SpiLiquidacao> EnviarPacs008(string pacs008Xml, CancellationToken ct)
    {
        var corpo = _signEnabled ? _assinatura.Assinar(pacs008Xml) : pacs008Xml;
        var content = new StringContent(corpo, Encoding.UTF8, "application/xml");
        var resp = await _http.PostAsync("/spi/pacs008", content, ct);
        var pacs002 = await resp.Content.ReadAsStringAsync(ct);

        // Não-repúdio: a pacs.002 do regulador tem que vir assinada pelo CERTPIA dele.
        if (_signEnabled && !_assinatura.Verificar(pacs002))
            return new SpiLiquidacao(false, "RJCT", "FF01", pacs002);

        var (status, reason) = ParsePacs002(pacs002);
        return new SpiLiquidacao(status == "ACSC", status, reason, pacs002);
    }

    public async Task<bool> EnviarPacs004(string pacs004Xml, CancellationToken ct)
    {
        var corpo = _signEnabled ? _assinatura.Assinar(pacs004Xml) : pacs004Xml;
        var content = new StringContent(corpo, Encoding.UTF8, "application/xml");
        var resp = await _http.PostAsync("/spi/pacs004", content, ct);
        var pacs002 = await resp.Content.ReadAsStringAsync(ct);
        if (_signEnabled && !_assinatura.Verificar(pacs002)) return false;
        var (status, _) = ParsePacs002(pacs002);
        return status == "ACSC";
    }

    private static (string Status, string? Reason) ParsePacs002(string xml)
    {
        try
        {
            var doc = XDocument.Parse(xml);
            var status = doc.Descendants(NsPacs002 + "TxSts").FirstOrDefault()?.Value ?? "RJCT";
            var reason = doc.Descendants(NsPacs002 + "Cd").FirstOrDefault()?.Value;
            return (status, reason);
        }
        catch
        {
            return ("RJCT", "FF01");
        }
    }
}
