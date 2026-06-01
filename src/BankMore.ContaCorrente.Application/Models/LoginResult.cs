namespace BankMore.ContaCorrente.Application.Models
{
    public class LoginResult
    {
        public bool Autenticado { get; set; }
        public string? Token { get; set; }
        public string? Mensagem { get; set; }
        public string? IdContaCorrente { get; set; }
        public int? NumeroConta { get; set; }
        public string? NomeTitular { get; set; }
        public string? Cpf { get; set; } // Adicionado para o Dashboard buscar saldo/extrato
    }
}
