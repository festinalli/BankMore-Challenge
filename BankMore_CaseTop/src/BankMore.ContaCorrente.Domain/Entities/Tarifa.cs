namespace BankMore.ContaCorrente.Domain.Entities
{
    public class Tarifa
    {
        public string Id { get; set; } = Guid.NewGuid().ToString();
        public string IdContaCorrente { get; set; } = string.Empty;
        public int NumeroConta { get; set; }
        public decimal Valor { get; set; }
        public DateTime DataProcessamento { get; set; } = DateTime.UtcNow;
        public int TipoTransferencia { get; set; }
        public string? TransferenciaId { get; set; }
    }
}
