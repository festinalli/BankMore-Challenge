using MediatR;
using BankMore.ContaCorrente.Application.Models;
using BankMore.ContaCorrente.Domain.Interfaces;
using Dapper;
using Npgsql;
using Microsoft.Extensions.Configuration;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record ObterExtratoQuery(string Cpf) : IRequest<ObterExtratoResponse>;

    public class ObterExtratoHandler(IConfiguration configuration, IContaCorrenteRepository repository) : IRequestHandler<ObterExtratoQuery, ObterExtratoResponse>
    {
        public async Task<ObterExtratoResponse> Handle(ObterExtratoQuery request, CancellationToken cancellationToken)
        {
            var connectionString = configuration.GetConnectionString("DefaultConnection");
            using var connection = new NpgsqlConnection(connectionString);

            var conta = await repository.ObterPorCpf(request.Cpf);
            if (conta == null) return new ObterExtratoResponse();

            var idConta = conta.IdContaCorrente;
            var saldoAtual = await repository.ObterSaldo(idConta);

            // 1. Busca Movimentos (Transferências)
            var movimentosDb = await connection.QueryAsync<MovimentoDb>(
                "SELECT datamovimento, tipomovimento, valor FROM movimento WHERE idcontacorrente = @Id", new { Id = idConta });

            // 2. Busca Tarifas (Processadas pelo Worker)
            var tarifasDb = await connection.QueryAsync<TarifaDb>(
                "SELECT valor, dataprocessamento, tipotransferencia FROM tarifa WHERE idcontacorrente = @Id", new { Id = idConta });

            var extrato = new List<MovimentoExtrato>();

            // Mapeia Movimentos usando a lógica de negócio
            foreach (var m in movimentosDb)
            {
                extrato.Add(new MovimentoExtrato
                {
                    Data = m.DataMovimento,
                    Tipo = m.TipoMovimento == "C" ? "Crédito" : "Débito",
                    Valor = m.Valor,
                    Descricao = m.TipoMovimento == "C" ? "Transferência Recebida" : "Transferência Enviada"
                });
            }

            // Mapeia Tarifas usando os Enums/Tipos de Transferência
            foreach (var t in tarifasDb)
            {
                if (t.Valor > 0)
                {
                    extrato.Add(new MovimentoExtrato
                    {
                        Data = t.DataProcessamento,
                        Tipo = "Débito",
                        Valor = t.Valor,
                        Descricao = ObterDescricaoTarifa(t.TipoTransferencia)
                    });
                }
            }

            return new ObterExtratoResponse
            {
                NomeTitular = conta.Nome,
                SaldoAtual = saldoAtual,
                Movimentos = extrato.OrderByDescending(x => x.Data).ToList()
            };
        }

        // Mantendo a lógica de descrição baseada no tipo da transferência (Enum)
        private string ObterDescricaoTarifa(int tipo)
        {
            return tipo switch
            {
                0 => "Tarifa Bancária - PIX",
                1 => "Tarifa Bancária - TED",
                2 => "Tarifa Bancária - TEF",
                _ => "Tarifa Bancária"
            };
        }
    }

    // Classes de mapeamento para o Dapper (POCOs)
    public class MovimentoDb
    {
        public string DataMovimento { get; set; } = string.Empty;
        public string TipoMovimento { get; set; } = string.Empty;
        public decimal Valor { get; set; }
    }

    public class TarifaDb
    {
        public decimal Valor { get; set; }
        public string DataProcessamento { get; set; } = string.Empty;
        public int TipoTransferencia { get; set; }
    }
}
