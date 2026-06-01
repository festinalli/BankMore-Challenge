namespace BankMore.Transferencia.Domain;

public class Transferencia
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string CorrelationId { get; set; } = string.Empty;
    public string CpfOrigem { get; set; } = string.Empty;
    public string CpfDestino { get; set; } = string.Empty;
    public decimal Valor { get; set; }
    public string Tipo { get; set; } = "PIX"; // PIX | TED | TEF
    public string Status { get; set; } = "SOLICITADA"; // SOLICITADA | APROVADA | REJEITADA | EFETIVADA | COMPENSADA
    public string? Motivo { get; set; }
    public decimal? ScoreFraude { get; set; }
    public string? ModeloVersao { get; set; }
    public DateTime SolicitadaEm { get; set; } = DateTime.UtcNow;
    public DateTime? DecididaEm { get; set; }
    public DateTime? EfetivadaEm { get; set; }
}
