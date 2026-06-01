using System;
using System.Collections.Generic;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Domain.Interfaces;
using BankMore.ContaCorrente.Application.Services;
using BankMore.ContaCorrente.Application.Models;
using MediatR;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

// Alias para resolver conflito: namespace "ContaCorrente" vs classe "ContaCorrente"
using ContaCorrenteEntity = BankMore.ContaCorrente.Domain.Entities.ContaCorrente;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record LoginCommand(string Cpf, string Senha) : IRequest<LoginResult>;

    /// <summary>
    /// Handler para autenticação de contas.
    /// 
    /// Responsabilidades:
    /// - Validar credenciais
    /// - Verificar se conta está ativa
    /// - Gerar JWT token
    /// 
    /// Segurança:
    /// - Mensagens de erro genéricas
    /// - Token com expiração
    /// - Password hashing com salt
    /// 
    /// Padrão: CQRS + MediatR
    /// </summary>
    public class LoginHandler : IRequestHandler<LoginCommand, LoginResult>
    {
        private readonly IContaCorrenteRepository _repository;
        private readonly IPasswordHasher _passwordHasher;
        private readonly IConfiguration _configuration;

        private const int TokenExpirationHours = 2;
        private const string DefaultJwtSecret = "UmaChaveMuitoSecretaEIgualParaTodasAsApis123";

        public LoginHandler(
            IContaCorrenteRepository repository,
            IPasswordHasher passwordHasher,
            IConfiguration configuration)
        {
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
            _passwordHasher = passwordHasher ?? throw new ArgumentNullException(nameof(passwordHasher));
            _configuration = configuration ?? throw new ArgumentNullException(nameof(configuration));
        }

        public async Task<LoginResult> Handle(LoginCommand request, CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(request.Cpf) || request.Cpf.Length != 11)
                return FailedLogin("Credenciais inválidas");

            if (string.IsNullOrWhiteSpace(request.Senha))
                return FailedLogin("Credenciais inválidas");

            var conta = await _repository.ObterPorCpf(request.Cpf);
            if (conta == null)
                return FailedLogin("Credenciais inválidas");

            if (!conta.EstaAtiva())
                return FailedLogin("Conta inativa");

            if (!_passwordHasher.VerifyPassword(request.Senha, conta.Senha, conta.Salt))
                return FailedLogin("Credenciais inválidas");

            var token = GenerateToken(conta);

            return new LoginResult
            {
                Autenticado = true,
                Token = token,
                IdContaCorrente = conta.IdContaCorrente,
                NumeroConta = conta.Numero,
                NomeTitular = conta.Nome,
                Cpf = conta.Cpf,
                Mensagem = "Login realizado com sucesso"
            };
        }

        private string GenerateToken(ContaCorrenteEntity conta)
        {
            var secret = _configuration["Jwt:Key"] ?? DefaultJwtSecret;
            var key = Encoding.ASCII.GetBytes(secret);

            var tokenHandler = new JwtSecurityTokenHandler();
            var descriptor = new SecurityTokenDescriptor
            {
                Subject = new ClaimsIdentity(BuildClaims(conta)),
                Expires = DateTime.UtcNow.AddHours(TokenExpirationHours),
                SigningCredentials = new SigningCredentials(
                    new SymmetricSecurityKey(key),
                    SecurityAlgorithms.HmacSha256Signature)
            };

            var token = tokenHandler.CreateToken(descriptor);
            return tokenHandler.WriteToken(token);
        }

        private static IEnumerable<Claim> BuildClaims(ContaCorrenteEntity conta)
        {
            return new[]
            {
                new Claim("id", conta.IdContaCorrente),
                new Claim("numero", conta.Numero.ToString()),
                new Claim(ClaimTypes.Name, conta.Nome),
                new Claim("cpf", conta.Cpf),
                new Claim(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString())
            };
        }

        private static LoginResult FailedLogin(string mensagem)
        {
            return new LoginResult
            {
                Autenticado = false,
                Mensagem = mensagem,
                Token = string.Empty
            };
        }
    }
}
