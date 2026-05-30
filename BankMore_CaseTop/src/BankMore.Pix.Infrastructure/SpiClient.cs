using System.Text;
using System.Xml.Linq;
using BankMore.Pix.Domain;

namespace BankMore.Pix.Infrastructure;

/// <summary>HTTP client do SPI no bacen-sim (envia pacs.008/004, lê pacs.002).</summary>
public sealed class SpiClient : ISpiClient
{
    private static readonly XNamespace NsPacs002 = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10";
    private readonly HttpClient _http;

    public SpiClient(HttpClient http) => _http = http;

    public async Task<SpiLiquidacao> EnviarPacs008(string pacs008Xml, CancellationToken ct)
    {
        var content = new StringContent(pacs008Xml, Encoding.UTF8, "application/xml");
        var resp = await _http.PostAsync("/spi/pacs008", content, ct);
        var pacs002 = await resp.Content.ReadAsStringAsync(ct);

        var (status, reason) = ParsePacs002(pacs002);
        return new SpiLiquidacao(status == "ACSC", status, reason, pacs002);
    }

    public async Task<bool> EnviarPacs004(string pacs004Xml, CancellationToken ct)
    {
        var content = new StringContent(pacs004Xml, Encoding.UTF8, "application/xml");
        var resp = await _http.PostAsync("/spi/pacs004", content, ct);
        var pacs002 = await resp.Content.ReadAsStringAsync(ct);
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
