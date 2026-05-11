using System;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;
using MediatR;
using BankMore.ContaCorrente.Application.Services;

// Alias para resolver conflito: namespace "ContaCorrente" vs classe "ContaCorrente"
using ContaCorrenteEntity = BankMore.ContaCorrente.Domain.Entities.ContaCorrente;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record CadastrarContaCommand(
        string Nome, 
        string Cpf, 
        string Senha, 
        decimal SaldoInicial
    ) : IRequest<CadastrarContaResponse>;

    public class CadastrarContaResponse
    {
        public string IdContaCorrente { get; set; } = string.Empty;
        public int NumeroConta { get; set; }
        public string NomeTitular { get; set; } = string.Empty;
        public string Cpf { get; set; } = string.Empty;
    }

    /// <summary>
    /// Handler para cadastro de conta corrente.
    /// 
    /// Responsabilidades:
    /// - Validar entrada
    /// - Verificar duplicatas
    /// - Criar conta com valores padrão
    /// - Registrar saldo inicial
    /// 
    /// Padrão: CQRS + MediatR
    /// </summary>
    public class CadastrarContaHandler : IRequestHandler<CadastrarContaCommand, CadastrarContaResponse>
    {
        private readonly IContaCorrenteRepository _repository;
        private readonly IPasswordHasher _passwordHasher;

        public CadastrarContaHandler(
            IContaCorrenteRepository repository, 
            IPasswordHasher passwordHasher)
        {
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
            _passwordHasher = passwordHasher ?? throw new ArgumentNullException(nameof(passwordHasher));
        }

        public async Task<CadastrarContaResponse> Handle(
            CadastrarContaCommand request, 
            CancellationToken cancellationToken)
        {
            ValidarEntrada(request);

            var contaExistente = await _repository.ObterPorCpf(request.Cpf);
            if (contaExistente != null)
                throw new InvalidOperationException($"CPF {request.Cpf} já cadastrado");

            var novaConta = CriarNovaConta(request);
            await _repository.Cadastrar(novaConta);

            if (request.SaldoInicial > 0)
                await RegistrarSaldoInicial(novaConta, request.SaldoInicial);

            return new CadastrarContaResponse
            {
                IdContaCorrente = novaConta.IdContaCorrente,
                NumeroConta = novaConta.Numero,
                NomeTitular = novaConta.Nome,
                Cpf = novaConta.Cpf
            };
        }

        private static void ValidarEntrada(CadastrarContaCommand request)
        {
            if (string.IsNullOrWhiteSpace(request.Cpf) || request.Cpf.Length != 11)
                throw new ArgumentException("CPF inválido");

            if (string.IsNullOrWhiteSpace(request.Nome))
                throw new ArgumentException("Nome obrigatório");

            if (string.IsNullOrWhiteSpace(request.Senha) || request.Senha.Length < 6)
                throw new ArgumentException("Senha deve ter mín. 6 caracteres");

            if (request.SaldoInicial < 0)
                throw new ArgumentException("Saldo não pode ser negativo");
        }

        private ContaCorrenteEntity CriarNovaConta(CadastrarContaCommand request)
        {
            var salt = Guid.NewGuid().ToString().Substring(0, 8);
            var senhaHash = _passwordHasher.HashPassword(request.Senha, salt);

            return new ContaCorrenteEntity
            {
                IdContaCorrente = Guid.NewGuid().ToString(),
                Cpf = request.Cpf,
                Nome = request.Nome.Trim(),
                Salt = salt,
                Senha = senhaHash,
                Numero = new Random().Next(100000, 999999),
                Ativo = true
            };
        }

        private async Task RegistrarSaldoInicial(ContaCorrenteEntity conta, decimal saldoInicial)
        {
            var movimento = new Movimento
            {
                IdMovimento = Guid.NewGuid().ToString(),
                IdContaCorrente = conta.IdContaCorrente,
                NumeroConta = conta.Numero,
                DataMovimento = DateTime.UtcNow,
                TipoMovimento = "C",
                Valor = saldoInicial,
                Categoria = "SALDO_INICIAL"
            };

            await _repository.AdicionarMovimento(movimento);
        }
    }
}
