using System;

namespace BankMore.ContaCorrente.Domain.Entities
{
    /// <summary>
    /// Entidade de domínio que representa uma Conta Corrente.
    /// 
    /// Padrão de Design:
    /// - Usa tipos semanticamente corretos (bool para Ativo, não int)
    /// - Conversão para tipos de banco ocorre na camada de persistência
    /// - Segue princípios de Domain-Driven Design (DDD)
    /// - Encapsula lógica de negócio relacionada a contas
    /// </summary>
    public class ContaCorrente
    {
        /// <summary>
        /// Identificador único da conta (GUID).
        /// </summary>
        public string IdContaCorrente { get; set; } = Guid.NewGuid().ToString();

        /// <summary>
        /// Número da conta (6 dígitos, único).
        /// </summary>
        public int Numero { get; set; }

        /// <summary>
        /// Nome do titular da conta.
        /// </summary>
        public string Nome { get; set; } = string.Empty;

        /// <summary>
        /// CPF do titular (11 dígitos, único).
        /// </summary>
        public string Cpf { get; set; } = string.Empty;

        /// <summary>
        /// Senha hasheada do titular.
        /// </summary>
        public string Senha { get; set; } = string.Empty;

        /// <summary>
        /// Salt para o hash da senha (segurança).
        /// </summary>
        public string Salt { get; set; } = string.Empty;

        /// <summary>
        /// Indica se a conta está ativa.
        /// ✅ Usa bool (tipo semanticamente correto)
        /// A conversão para int ocorre no Repository (camada de persistência)
        /// </summary>
        public bool Ativo { get; set; } = true;

        /// <summary>
        /// Construtor padrão.
        /// </summary>
        public ContaCorrente() { }

        /// <summary>
        /// Construtor com parâmetros principais.
        /// </summary>
        public ContaCorrente(string nome, string cpf, string senha, int numero)
        {
            if (string.IsNullOrWhiteSpace(nome))
                throw new ArgumentException("Nome não pode ser nulo ou vazio", nameof(nome));
            
            if (string.IsNullOrWhiteSpace(cpf) || cpf.Length != 11)
                throw new ArgumentException("CPF deve ter 11 dígitos", nameof(cpf));
            
            if (string.IsNullOrWhiteSpace(senha) || senha.Length < 6)
                throw new ArgumentException("Senha deve ter no mínimo 6 caracteres", nameof(senha));
            
            if (numero <= 0)
                throw new ArgumentException("Número da conta deve ser maior que zero", nameof(numero));

            IdContaCorrente = Guid.NewGuid().ToString();
            Nome = nome.Trim();
            Cpf = cpf;
            Senha = senha;
            Salt = Guid.NewGuid().ToString().Substring(0, 8);
            Numero = numero;
            Ativo = true;
        }

        /// <summary>
        /// Inativa a conta (soft delete).
        /// </summary>
        public void Inativar()
        {
            Ativo = false;
        }

        /// <summary>
        /// Reativa uma conta inativa.
        /// </summary>
        public void Reativar()
        {
            Ativo = true;
        }

        /// <summary>
        /// Verifica se a conta está ativa.
        /// </summary>
        public bool EstaAtiva() => Ativo;
    }
}
