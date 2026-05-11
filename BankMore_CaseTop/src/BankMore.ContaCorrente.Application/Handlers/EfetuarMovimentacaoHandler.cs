using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;
using MediatR;

namespace BankMore.ContaCorrente.Application.Handlers
{
    public record EfetuarMovimentacaoCommand(
        string RequestId,
        string Cpf,
        decimal Valor,
        string Tipo
    ) : IRequest<bool>;

    public class EfetuarMovimentacaoHandler(IContaCorrenteRepository repository)
        : IRequestHandler<EfetuarMovimentacaoCommand, bool>
    {
        public async Task<bool> Handle(EfetuarMovimentacaoCommand request, CancellationToken cancellationToken)
        {
            if (await repository.ExisteChaveIdempotencia(request.RequestId))
                return true;

            if (request.Valor <= 0)
                throw new ArgumentException("Valor deve ser positivo");

            if (request.Tipo != "C" && request.Tipo != "D")
                throw new ArgumentException("Tipo deve ser 'C' (crédito) ou 'D' (débito)");

            var conta = await repository.ObterPorCpf(request.Cpf)
                ?? throw new ArgumentException("Conta não encontrada");

            if (!conta.Ativo)
                throw new ArgumentException("Conta inativa");

            var movimento = new Movimento
            {
                IdMovimento = Guid.NewGuid().ToString(),
                IdContaCorrente = conta.IdContaCorrente,
                NumeroConta = conta.Numero,
                DataMovimento = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss"),
                TipoMovimento = request.Tipo,
                Valor = request.Valor
            };

            await repository.AdicionarMovimento(movimento);

            await repository.SalvarIdempotencia(new Idempotencia
            {
                ChaveIdempotencia = request.RequestId,
                Requisicao = $"{request.Cpf}:{request.Tipo}:{request.Valor}",
                Resultado = "OK"
            });

            return true;
        }
    }
}
