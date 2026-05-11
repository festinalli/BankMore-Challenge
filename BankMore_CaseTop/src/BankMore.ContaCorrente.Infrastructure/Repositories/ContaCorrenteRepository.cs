using System;
using System.Collections.Generic;
using System.Data;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;
using Dapper;
using Npgsql;

// Alias para resolver conflito: namespace "ContaCorrente" vs classe "ContaCorrente"
using ContaCorrenteEntity = BankMore.ContaCorrente.Domain.Entities.ContaCorrente;

namespace BankMore.ContaCorrente.Infrastructure.Repositories
{
    /// <summary>
    /// Repository para persistência de Contas Correntes no PostgreSQL.
    /// 
    /// Responsabilidades:
    /// - Abstração do acesso ao banco de dados
    /// - Conversão entre domínio (bool) e persistência (int)
    /// - Implementação do padrão Repository
    /// 
    /// Padrão: Repository Pattern + DTO + Clean Architecture
    /// </summary>
    public class ContaCorrenteRepository : IContaCorrenteRepository
    {
        private readonly string _connectionString;

        public ContaCorrenteRepository(string connectionString)
        {
            if (string.IsNullOrWhiteSpace(connectionString))
                throw new ArgumentException("Connection string não pode ser nula ou vazia", nameof(connectionString));
            
            _connectionString = connectionString;
        }

        private IDbConnection CreateConnection() => new NpgsqlConnection(_connectionString);

        public async Task<ContaCorrenteEntity?> ObterPorCpf(string cpf)
        {
            if (string.IsNullOrWhiteSpace(cpf))
                throw new ArgumentException("CPF não pode ser nulo ou vazio", nameof(cpf));

            using var db = CreateConnection();
            const string sql = "SELECT * FROM contacorrente WHERE cpf = @cpf";
            var dto = await db.QueryFirstOrDefaultAsync<ContaCorrenteDto>(sql, new { cpf });
            return dto?.ToEntity();
        }

        public async Task<ContaCorrenteEntity?> ObterPorNumero(int numero)
        {
            if (numero <= 0)
                throw new ArgumentException("Número da conta deve ser maior que zero", nameof(numero));

            using var db = CreateConnection();
            const string sql = "SELECT * FROM contacorrente WHERE numero = @numero";
            var dto = await db.QueryFirstOrDefaultAsync<ContaCorrenteDto>(sql, new { numero });
            return dto?.ToEntity();
        }

        public async Task<ContaCorrenteEntity?> ObterPorId(string id)
        {
            if (string.IsNullOrWhiteSpace(id))
                throw new ArgumentException("ID não pode ser nulo ou vazio", nameof(id));

            using var db = CreateConnection();
            const string sql = "SELECT * FROM contacorrente WHERE idcontacorrente = @id";
            var dto = await db.QueryFirstOrDefaultAsync<ContaCorrenteDto>(sql, new { id });
            return dto?.ToEntity();
        }

        public async Task<string> Cadastrar(ContaCorrenteEntity conta)
        {
            if (conta == null)
                throw new ArgumentNullException(nameof(conta));

            using var db = CreateConnection();
            
            var dto = new ContaCorrenteDto
            {
                IdContaCorrente = conta.IdContaCorrente,
                Numero = conta.Numero,
                Nome = conta.Nome,
                Cpf = conta.Cpf,
                Senha = conta.Senha,
                Salt = conta.Salt,
                Ativo = conta.Ativo ? 1 : 0
            };

            const string sql = @"
                INSERT INTO contacorrente 
                    (idcontacorrente, numero, nome, cpf, senha, salt, ativo) 
                VALUES 
                    (@IdContaCorrente, @Numero, @Nome, @Cpf, @Senha, @Salt, @Ativo)";
            
            await db.ExecuteAsync(sql, dto);
            return conta.Numero.ToString();
        }

        public async Task Inativar(string id)
        {
            if (string.IsNullOrWhiteSpace(id))
                throw new ArgumentException("ID não pode ser nulo ou vazio", nameof(id));

            using var db = CreateConnection();
            const string sql = "UPDATE contacorrente SET ativo = 0 WHERE idcontacorrente = @id";
            await db.ExecuteAsync(sql, new { id });
        }

        public async Task AdicionarMovimento(Movimento movimento)
        {
            if (movimento == null)
                throw new ArgumentNullException(nameof(movimento));

            using var db = CreateConnection();
            const string sql = @"
                INSERT INTO movimento
                    (idmovimento, idcontacorrente, numeroconta, datamovimento, tipomovimento, valor, categoria, transferencia_id)
                VALUES
                    (@IdMovimento, @IdContaCorrente, @NumeroConta, @DataMovimento, @TipoMovimento, @Valor, @Categoria, @TransferenciaId)";

            await db.ExecuteAsync(sql, movimento);
        }

        public async Task<decimal> ObterSaldo(string idContaCorrente)
        {
            if (string.IsNullOrWhiteSpace(idContaCorrente))
                throw new ArgumentException("ID da conta não pode ser nulo ou vazio", nameof(idContaCorrente));

            using var db = CreateConnection();
            const string sql = @"
                SELECT 
                    COALESCE(SUM(CASE WHEN tipomovimento = 'C' THEN valor ELSE 0 END), 0) - 
                    COALESCE(SUM(CASE WHEN tipomovimento = 'D' THEN valor ELSE 0 END), 0) 
                FROM movimento 
                WHERE idcontacorrente = @idContaCorrente";
            
            return await db.ExecuteScalarAsync<decimal>(sql, new { idContaCorrente });
        }

        public async Task<IEnumerable<Movimento>> ObterMovimentos(string idContaCorrente)
        {
            if (string.IsNullOrWhiteSpace(idContaCorrente))
                throw new ArgumentException("ID da conta não pode ser nulo ou vazio", nameof(idContaCorrente));

            using var db = CreateConnection();
            const string sql = @"
                SELECT * FROM movimento 
                WHERE idcontacorrente = @idContaCorrente 
                ORDER BY datamovimento DESC";
            
            return await db.QueryAsync<Movimento>(sql, new { idContaCorrente });
        }

        public async Task<IEnumerable<Tarifa>> ObterTarifas(int numeroConta)
        {
            if (numeroConta <= 0)
                throw new ArgumentException("Número da conta deve ser maior que zero", nameof(numeroConta));

            using var db = CreateConnection();
            const string sql = @"
                SELECT * FROM tarifa 
                WHERE numeroconta = @numeroConta 
                ORDER BY dataprocessamento DESC";
            
            return await db.QueryAsync<Tarifa>(sql, new { numeroConta });
        }

        public async Task<bool> ExisteChaveIdempotencia(string chave)
        {
            if (string.IsNullOrWhiteSpace(chave))
                throw new ArgumentException("Chave não pode ser nula ou vazia", nameof(chave));

            using var db = CreateConnection();
            const string sql = "SELECT COUNT(1) FROM idempotencia WHERE chave_idempotencia = @chave";
            var count = await db.ExecuteScalarAsync<int>(sql, new { chave });
            return count > 0;
        }

        public async Task SalvarIdempotencia(Idempotencia idempotencia)
        {
            if (idempotencia == null)
                throw new ArgumentNullException(nameof(idempotencia));

            using var db = CreateConnection();
            const string sql = @"
                INSERT INTO idempotencia 
                    (chave_idempotencia, requisicao, resultado, data_processamento) 
                VALUES 
                    (@ChaveIdempotencia, @Requisicao, @Resultado, @DataProcessamento)";
            
            await db.ExecuteAsync(sql, idempotencia);
        }
    }

    /// <summary>
    /// DTO (Data Transfer Object) para mapeamento entre banco de dados e domínio.
    /// 
    /// Responsabilidades:
    /// - Representar a estrutura exata da tabela no banco
    /// - Converter para/de entidades de domínio
    /// - Isolar mudanças no schema do banco do domínio
    /// 
    /// Padrão: DTO Pattern
    /// </summary>
    internal class ContaCorrenteDto
    {
        public string IdContaCorrente { get; set; } = string.Empty;
        public int Numero { get; set; }
        public string Nome { get; set; } = string.Empty;
        public string Cpf { get; set; } = string.Empty;
        public string Senha { get; set; } = string.Empty;
        public string Salt { get; set; } = string.Empty;
        public int Ativo { get; set; }

        /// <summary>
        /// Converte DTO para entidade de domínio.
        /// Conversão: int (banco) → bool (domínio)
        /// </summary>
        public ContaCorrenteEntity ToEntity() => new ContaCorrenteEntity
        {
            IdContaCorrente = IdContaCorrente,
            Numero = Numero,
            Nome = Nome,
            Cpf = Cpf,
            Senha = Senha,
            Salt = Salt,
            Ativo = Ativo == 1
        };
    }
}
