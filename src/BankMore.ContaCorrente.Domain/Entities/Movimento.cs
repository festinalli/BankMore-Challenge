namespace BankMore.ContaCorrente.Domain.Entities
{
    public class Movimento
    {
        public string IdMovimento { get; set; } = Guid.NewGuid().ToString();
        public string IdContaCorrente { get; set; } = string.Empty;
        public int NumeroConta { get; set; }
        public DateTime DataMovimento { get; set; } = DateTime.UtcNow;
        public string TipoMovimento { get; set; } = string.Empty; // C ou D
        public decimal Valor { get; set; }
        public string Categoria { get; set; } = "MOVIMENTO";
        public string? TransferenciaId { get; set; }
    }
}
