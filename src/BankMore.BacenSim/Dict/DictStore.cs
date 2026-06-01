using System.Collections.Concurrent;

namespace BankMore.BacenSim.Dict;

/// <summary>
/// DICT — Diretório de Identificadores de Contas Transacionais.
///
/// No PIX real, o DICT é um serviço centralizado no BACEN que mapeia uma chave
/// (CPF, CNPJ, e-mail, telefone, EVP-aleatória) → dados da conta (ISPB, agência,
/// conta, titular). Todo pagamento por chave consulta o DICT primeiro.
///
/// Aqui é in-memory thread-safe (ConcurrentDictionary). Numa instalação real teria
/// persistência, replicação e o fluxo de claims (portabilidade/reivindicação) com
/// SLA de 7 dias úteis — modelamos o claim de forma simplificada (resolução imediata).
/// </summary>
public sealed class DictStore
{
    private readonly ConcurrentDictionary<string, DictEntry> _entries = new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentDictionary<string, DictClaim> _claims = new();

    public DictEntry? Resolver(string chave) =>
        _entries.TryGetValue(chave, out var e) && e.Status == "ATIVA" ? e : null;

    public DictEntry Registrar(string chave, string tipo, string ispb, string cpfTitular, string nomeTitular)
    {
        var entry = new DictEntry(chave, tipo, ispb, cpfTitular, nomeTitular, "ATIVA", DateTimeOffset.UtcNow);
        // AddOrUpdate: registrar é idempotente pro mesmo titular; troca de dono vai por claim.
        return _entries.AddOrUpdate(chave, entry, (_, existing) =>
            existing.CpfTitular == cpfTitular ? entry : existing);
    }

    public bool Remover(string chave, string cpfTitular)
    {
        if (_entries.TryGetValue(chave, out var e) && e.CpfTitular == cpfTitular)
            return _entries.TryRemove(chave, out _);
        return false;
    }

    /// <summary>
    /// Claim de portabilidade/reivindicação. No BACEN real abre janela de 7 dias úteis
    /// pro PSP doador confirmar/contestar. Aqui resolvemos na hora (status RESOLVIDO),
    /// transferindo a posse da chave — o suficiente pra demonstrar o fluxo.
    /// </summary>
    public DictClaim AbrirClaim(string chave, string tipoClaim, string ispbReivindicador, string cpfReivindicador, string nomeReivindicador)
    {
        var claimId = Guid.NewGuid().ToString("N");
        var claim = new DictClaim(claimId, chave, tipoClaim, ispbReivindicador, cpfReivindicador, "RESOLVIDO", DateTimeOffset.UtcNow);
        _claims[claimId] = claim;
        // Transfere posse imediatamente (simplificação da janela de 7 dias)
        _entries[chave] = new DictEntry(chave,
            _entries.TryGetValue(chave, out var prev) ? prev.Tipo : "EVP",
            ispbReivindicador, cpfReivindicador, nomeReivindicador, "ATIVA", DateTimeOffset.UtcNow);
        return claim;
    }

    public IReadOnlyCollection<DictEntry> Listar() => _entries.Values.ToList();
}

public sealed record DictEntry(
    string Chave, string Tipo, string Ispb, string CpfTitular, string NomeTitular,
    string Status, DateTimeOffset CriadoEm);

public sealed record DictClaim(
    string Id, string Chave, string TipoClaim, string IspbReivindicador,
    string CpfReivindicador, string Status, DateTimeOffset CriadoEm);
