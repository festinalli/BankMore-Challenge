using MediatR;
using BankMore.ContaCorrente.Application.Models;
using BankMore.ContaCorrente.Domain.Interfaces;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record ObterExtratoQuery(string Cpf) : IRequest<ObterExtratoResponse>;

    /// <summary>
    /// Retorna o extrato do titular. Saldo é calculado por SUM(movimento C - D) — fonte única.
    /// Tarifas já estão refletidas em movimento (categoria=TARIFA), então NÃO somamos tarifa separada.
    /// </summary>
    public class ObterExtratoHandler(IContaCorrenteRepository repository)
        : IRequestHandler<ObterExtratoQuery, ObterExtratoResponse>
    {
        public async Task<ObterExtratoResponse> Handle(ObterExtratoQuery request, CancellationToken cancellationToken)
        {
            var conta = await repository.ObterPorCpf(request.Cpf);
            if (conta == null) return new ObterExtratoResponse();

            var saldo = await repository.ObterSaldo(conta.IdContaCorrente);
            var movimentos = await repository.ObterMovimentos(conta.IdContaCorrente);

            var extrato = movimentos.Select(m => new MovimentoExtrato
            {
                Data = m.DataMovimento.ToString("yyyy-MM-dd HH:mm:ss"),
                Tipo = m.TipoMovimento == "C" ? "Crédito" : "Débito",
                Valor = m.Valor,
                Descricao = DescreverMovimento(m.Categoria, m.TipoMovimento)
            }).ToList();

            return new ObterExtratoResponse
            {
                NomeTitular = conta.Nome,
                SaldoAtual = saldo,
                Movimentos = extrato
            };
        }

        private static string DescreverMovimento(string categoria, string tipo) => categoria switch
        {
            "SALDO_INICIAL" => "Saldo inicial",
            "TRANSFERENCIA" => tipo == "C" ? "Transferência recebida" : "Transferência enviada",
            "TARIFA"        => "Tarifa de transferência",
            "MOVIMENTO"     => tipo == "C" ? "Depósito" : "Saque",
            _               => tipo == "C" ? "Crédito" : "Débito"
        };
    }
}
