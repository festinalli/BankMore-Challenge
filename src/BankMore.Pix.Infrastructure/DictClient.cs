using System.Net;
using System.Net.Http.Json;
using BankMore.Pix.Domain;

namespace BankMore.Pix.Infrastructure;

/// <summary>HTTP client do DICT no bacen-sim.</summary>
public sealed class DictClient : IDictClient
{
    private readonly HttpClient _http;

    public DictClient(HttpClient http) => _http = http;

    public async Task<DictResolucao?> ResolverChave(string chave, CancellationToken ct)
    {
        var resp = await _http.GetAsync($"/dict/entries/{Uri.EscapeDataString(chave)}", ct);
        if (resp.StatusCode == HttpStatusCode.NotFound) return null;
        resp.EnsureSuccessStatusCode();
        var dto = await resp.Content.ReadFromJsonAsync<DictEntryDto>(cancellationToken: ct);
        if (dto is null) return null;
        return new DictResolucao(dto.chave, dto.tipo, dto.ispb, dto.cpfTitular, dto.nomeTitular, dto.status);
    }

    public async Task RegistrarChave(string chave, string tipo, string cpfTitular, string nomeTitular, CancellationToken ct)
    {
        var resp = await _http.PostAsJsonAsync("/dict/entries",
            new { chave, tipo, ispb = "12345678", cpfTitular, nomeTitular }, ct);
        resp.EnsureSuccessStatusCode();
    }

    private sealed record DictEntryDto(
        string chave, string tipo, string ispb, string cpfMascarado,
        string cpfTitular, string nomeTitular, string status);
}
