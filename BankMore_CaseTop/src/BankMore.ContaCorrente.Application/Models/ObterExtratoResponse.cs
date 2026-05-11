using System.Collections.Generic;

namespace BankMore.ContaCorrente.Application.Models
{
    public class ObterExtratoResponse
    {
        public string NomeTitular { get; set; } = string.Empty;
        public decimal SaldoAtual { get; set; }
        public List<MovimentoExtrato> Movimentos { get; set; } = new List<MovimentoExtrato>();
    }

    public class MovimentoExtrato
    {
        public string Data { get; set; } = string.Empty;
        public string Tipo { get; set; } = string.Empty;
        public decimal Valor { get; set; }
        public string Descricao { get; set; } = string.Empty;
    }
}
