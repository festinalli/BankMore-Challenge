using System.Net.Http.Json;
using BankMore.Pix.Domain;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// HTTP client do fraud-ml (/predict). Computa as features do PIX e pede o score.
///
/// IMPORTANTE — timezone: o modelo XGBoost foi treinado com `hora_do_dia` em horário
/// local do Brasil. Usar UTC aqui causaria falsos positivos à noite (22h BRT = 01h UTC,
/// que o modelo aprendeu como "madrugada suspeita"). Por isso convertemos pra
/// America/Sao_Paulo antes de extrair hora/dow. (Foi exatamente o bug que detectamos
/// no fraud-detector PyFlink — aqui já nascemos corrigidos.)
///
/// Fail-open: se o ML cair, retorna null e o chamador segue só com as regras duras —
/// não derruba pagamentos legítimos por indisponibilidade do scoring.
/// </summary>
public sealed class FraudeClient : IFraudeClient
{
    private static readonly TimeZoneInfo TzBrasil = ResolveTz();
    private readonly HttpClient _http;

    public FraudeClient(HttpClient http) => _http = http;

    public async Task<FraudeScore?> Avaliar(
        string cpfOrigem, decimal valor, string tipo, int countTxRecente, CancellationToken ct)
    {
        var agoraBrt = TimeZoneInfo.ConvertTime(DateTimeOffset.UtcNow, TzBrasil);
        var body = new
        {
            cpfOrigem,
            features = new
            {
                valor = (double)valor,
                tipo = tipo.ToUpperInvariant(),
                hora_do_dia = agoraBrt.Hour,
                dow = (int)agoraBrt.DayOfWeek,
                count_tx_cpf_1h = countTxRecente,
                is_autotransferencia = 0,  // regra dura já filtrou antes de chegar aqui
            }
        };

        try
        {
            var resp = await _http.PostAsJsonAsync("/predict", body, ct);
            resp.EnsureSuccessStatusCode();
            var dto = await resp.Content.ReadFromJsonAsync<PredictDto>(cancellationToken: ct);
            if (dto is null) return null;
            return new FraudeScore(dto.score, dto.threshold, dto.modelo_versao ?? "ml-unknown", dto.decisao_recomendada ?? "");
        }
        catch
        {
            // Fail-open — indisponibilidade do ML não bloqueia o PIX
            return null;
        }
    }

    private static TimeZoneInfo ResolveTz()
    {
        foreach (var id in new[] { "America/Sao_Paulo", "E. South America Standard Time" })
        {
            try { return TimeZoneInfo.FindSystemTimeZoneById(id); }
            catch (TimeZoneNotFoundException) { }
            catch (InvalidTimeZoneException) { }
        }
        // Fallback: UTC-3 fixo (sem horário de verão, que o Brasil não usa desde 2019)
        return TimeZoneInfo.CreateCustomTimeZone("BRT", TimeSpan.FromHours(-3), "BRT", "BRT");
    }

    private sealed record PredictDto(double score, double threshold, string? modelo_versao, string? decisao_recomendada);
}
