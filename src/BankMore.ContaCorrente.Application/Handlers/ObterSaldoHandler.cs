using System;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Domain.Interfaces;
using MediatR;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record ObterSaldoQuery(string Cpf) : IRequest<SaldoResponse>;

    public class SaldoResponse
    {
        public int NumeroConta { get; set; }
        public string NomeTitular { get; set; } = string.Empty;
        public string DataHora { get; set; } = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss");
        public decimal Saldo { get; set; }
    }

    public class ObterSaldoHandler(IContaCorrenteRepository repository) : IRequestHandler<ObterSaldoQuery, SaldoResponse>
    {
        public async Task<SaldoResponse> Handle(ObterSaldoQuery request, CancellationToken cancellationToken)
        {
            // Busca a conta pelo CPF no repositório
            var conta = await repository.ObterPorCpf(request.Cpf);

            // Tratamento de segurança: Se a conta não existir ou estiver inativa, 
            // retornamos um objeto com saldo zero em vez de lançar uma exceção (throw).
            // Isso evita o erro 500 no Dashboard.
            if (conta == null || !conta.Ativo)
            {
                return new SaldoResponse
                {
                    NumeroConta = 0,
                    NomeTitular = "Conta não encontrada ou inativa",
                    Saldo = 0,
                    DataHora = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss")
                };
            }

            // Se a conta existe, busca o saldo real calculado pelos movimentos
            var saldo = await repository.ObterSaldo(conta.IdContaCorrente);
            
            return new SaldoResponse
            {
                NumeroConta = conta.Numero,
                NomeTitular = conta.Nome,
                Saldo = saldo,
                DataHora = DateTime.Now.ToString("dd/MM/yyyy HH:mm:ss")
            };
        }
    }
}
