using System;

namespace BankMore.ContaCorrente.Domain.Entities
{
    public class Movimento
    {
        public string IdMovimento { get; set; } = Guid.NewGuid().ToString();
        public string IdContaCorrente { get; set; } = string.Empty;
        public int NumeroConta { get; set; } 
        public string DataMovimento { get; set; } = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss");
        public string TipoMovimento { get; set; } = string.Empty; // C ou D
        public decimal Valor { get; set; }
    }
}
