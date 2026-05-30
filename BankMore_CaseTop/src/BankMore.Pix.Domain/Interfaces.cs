namespace BankMore.Pix.Domain;

/// <summary>Persistência do bounded context PIX (Dapper na Infrastructure).</summary>
public interface IPixRepository
{
    // Chaves
    Task<PixChave?> ObterChaveLocal(string valorChave, CancellationToken ct);
    Task SalvarChave(PixChave chave, CancellationToken ct);
    Task<IReadOnlyList<PixChave>> ListarChavesPorConta(string idContaCorrente, CancellationToken ct);

    // Pagamentos
    Task SalvarPagamento(PixPagamento p, CancellationToken ct);
    Task AtualizarPagamento(PixPagamento p, CancellationToken ct);
    Task<PixPagamento?> ObterPagamento(Guid id, CancellationToken ct);
    Task<PixPagamento?> ObterPagamentoPorE2e(string e2eId, CancellationToken ct);
    Task<int> ContarPagamentosRecentes(string cpfOrigem, TimeSpan janela, CancellationToken ct);

    // Liquidação atômica: debita origem + credita destino (movimentos) numa TX
    Task LiquidarMovimentos(string cpfOrigem, string? cpfDestino, decimal valor, string e2eId, CancellationToken ct);
    // Estorno da devolução: credita de volta a origem, debita destino
    Task EstornarMovimentos(string cpfOrigem, string? cpfDestino, decimal valor, string e2eId, CancellationToken ct);

    // QR Code
    Task SalvarQrCode(PixQrCode qr, CancellationToken ct);
    Task<PixQrCode?> ObterQrCodePorTxid(string txid, CancellationToken ct);
    Task AtualizarStatusQrCode(string txid, string status, CancellationToken ct);

    // MED
    Task SalvarDevolucao(PixDevolucao d, CancellationToken ct);
    Task AtualizarDevolucao(PixDevolucao d, CancellationToken ct);
    Task<PixDevolucao?> ObterDevolucao(Guid id, CancellationToken ct);

    // Consentimento
    Task SalvarConsentimento(PixConsentimento c, CancellationToken ct);
    Task AtualizarConsentimento(PixConsentimento c, CancellationToken ct);
    Task<PixConsentimento?> ObterConsentimento(Guid id, CancellationToken ct);
    Task<IReadOnlyList<PixConsentimento>> ListarConsentimentosVencidos(DateTimeOffset agora, CancellationToken ct);

    // NFC
    Task SalvarNfcToken(PixNfcToken t, CancellationToken ct);
    Task<PixNfcToken?> ObterNfcToken(string token, CancellationToken ct);
    Task AtualizarNfcToken(PixNfcToken t, CancellationToken ct);

    // Resolução de conta a partir do CPF (pra liquidação)
    Task<string?> ObterIdContaPorCpf(string cpf, CancellationToken ct);
    Task<string?> ObterNomePorCpf(string cpf, CancellationToken ct);
    Task<string?> ObterCpfPorIdConta(string idContaCorrente, CancellationToken ct);
}

/// <summary>Cliente HTTP do DICT no bacen-sim.</summary>
public interface IDictClient
{
    Task<DictResolucao?> ResolverChave(string chave, CancellationToken ct);
    Task RegistrarChave(string chave, string tipo, string cpfTitular, string nomeTitular, CancellationToken ct);
}

public sealed record DictResolucao(string Chave, string Tipo, string Ispb, string CpfTitular, string NomeTitular, string Status);

/// <summary>Cliente HTTP do SPI no bacen-sim (liquidação ISO 20022).</summary>
public interface ISpiClient
{
    Task<SpiLiquidacao> EnviarPacs008(string pacs008Xml, CancellationToken ct);
    Task<bool> EnviarPacs004(string pacs004Xml, CancellationToken ct);
}

public sealed record SpiLiquidacao(bool Sucesso, string Status, string? ReasonCode, string Pacs002Xml);

/// <summary>
/// Cliente do serviço de antifraude (fraud-ml). Scoring SÍNCRONO inline — o PIX é
/// instantâneo (&lt;10s), então a análise precisa decidir antes da liquidação.
/// </summary>
public interface IFraudeClient
{
    Task<FraudeScore?> Avaliar(string cpfOrigem, decimal valor, string tipo, int countTxRecente, CancellationToken ct);
}

/// <param name="Score">0-1, quanto maior mais suspeito.</param>
/// <param name="Threshold">limiar acima do qual o ML recomenda rejeitar.</param>
public sealed record FraudeScore(double Score, double Threshold, string ModeloVersao, string DecisaoRecomendada);
