using System;

namespace BankMore.ContaCorrente.Domain.Entities
{
    public class Tarifa
    {
        public string Id { get; set; } = Guid.NewGuid().ToString();
        public int NumeroConta { get; set; }
        public decimal Valor { get; set; }
        public string DataProcessamento { get; set; } = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss");
    }
}
