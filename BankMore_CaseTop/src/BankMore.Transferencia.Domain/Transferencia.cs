using System;

namespace BankMore.Transferencia.Domain
{
    public class Transferencia
    {
        public string IdTransferencia { get; set; } = Guid.NewGuid().ToString();
        public string IdContaCorrenteOrigem { get; set; } = string.Empty;
        public string IdContaCorrenteDestino { get; set; } = string.Empty;
        public string DataMovimento { get; set; } = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss");
        public decimal Valor { get; set; }
    }
}
