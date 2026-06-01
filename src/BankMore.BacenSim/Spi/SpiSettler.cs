using BankMore.BacenSim.Dict;
using BankMore.BacenSim.Iso20022;

namespace BankMore.BacenSim.Spi;

/// <summary>
/// SPI — Sistema de Pagamentos Instantâneos.
///
/// Liquida ordens pacs.008 e responde pacs.002. No PIX real o SPI faz a liquidação
/// bruta em tempo real (LBTR) nas contas Reservas Bancárias / Conta PI dos PSPs,
/// com SLA de liquidação < 10 segundos.
///
/// Validações que fazemos (reason codes ISO 20022 / Manual de Padrões do SPI):
///   - AC03  conta credor inválida (chave não existe no DICT)
///   - AM02  valor não permitido (<= 0)
///   - AB09  erro de instituição (ISPB destino inválido)
///   - FF07  fraude detectada (hook pra integração futura)
///
/// A latência é simulada (50-400ms) pra demonstrar o SLA <10s sem travar a demo.
/// </summary>
public sealed class SpiSettler
{
    private readonly DictStore _dict;
    private readonly ILogger<SpiSettler> _log;
    private static readonly Random _rng = new();

    public SpiSettler(DictStore dict, ILogger<SpiSettler> log)
    {
        _dict = dict;
        _log = log;
    }

    public async Task<SpiResult> LiquidarAsync(string pacs008Xml, CancellationToken ct)
    {
        Pacs008Parsed ordem;
        try
        {
            ordem = Iso20022Messages.ParsePacs008(pacs008Xml);
        }
        catch (Exception ex)
        {
            _log.LogWarning(ex, "pacs.008 malformado");
            return Rejeitar("", "", "FF01"); // formato inválido
        }

        var agora = DateTimeOffset.UtcNow;
        var respMsgId = "SPI" + Guid.NewGuid().ToString("N")[..20];

        // Latência de liquidação simulada (dentro do SLA de 10s)
        await Task.Delay(_rng.Next(50, 400), ct);

        // Validação 1: valor
        if (ordem.Valor <= 0)
            return Rejeitar(respMsgId, ordem, "AM02", agora);

        // Validação 2: ISPB destino presente
        if (string.IsNullOrWhiteSpace(ordem.IspbDestino))
            return Rejeitar(respMsgId, ordem, "AB09", agora);

        // Validação 3: CPF destino bate com algum titular do DICT?
        // (No fluxo real a chave já foi resolvida pelo PSP origem; aqui revalidamos
        //  a consistência cpfDestino↔DICT como o SPI faria contra a base de contas.)
        var destinoConhecido = _dict.Listar().Any(e => e.CpfTitular == ordem.CpfDestino);
        if (!destinoConhecido && ordem.IspbDestino == "12345678")  // só valida intra-BankMore
            return Rejeitar(respMsgId, ordem, "AC03", agora);

        var pacs002 = Iso20022Messages.BuildPacs002(
            respMsgId, ordem.MsgId, ordem.E2eId, "ACSC", null, agora);

        _log.LogInformation("SPI liquidou e2e={E2e} valor={Valor} {Org}->{Dst}",
            ordem.E2eId, ordem.Valor, ordem.IspbOrigem, ordem.IspbDestino);

        return new SpiResult(true, "ACSC", null, pacs002, ordem.E2eId, ordem.Valor);
    }

    private SpiResult Rejeitar(string respMsgId, Pacs008Parsed ordem, string reasonCode, DateTimeOffset agora)
    {
        var pacs002 = Iso20022Messages.BuildPacs002(
            respMsgId, ordem.MsgId, ordem.E2eId, "RJCT", reasonCode, agora);
        _log.LogWarning("SPI rejeitou e2e={E2e} motivo={Cd}", ordem.E2eId, reasonCode);
        return new SpiResult(false, "RJCT", reasonCode, pacs002, ordem.E2eId, ordem.Valor);
    }

    private SpiResult Rejeitar(string e2e, string msgId, string reasonCode)
    {
        var pacs002 = Iso20022Messages.BuildPacs002(
            "SPI" + Guid.NewGuid().ToString("N")[..20], msgId, e2e, "RJCT", reasonCode, DateTimeOffset.UtcNow);
        return new SpiResult(false, "RJCT", reasonCode, pacs002, e2e, 0);
    }
}

public sealed record SpiResult(
    bool Sucesso, string Status, string? ReasonCode, string Pacs002Xml,
    string E2eId, decimal Valor);
