using Xunit;
using Moq;
using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Domain.Interfaces;

namespace BankMore.ContaCorrente.Application.Tests;

public class ObterSaldoHandlerTests
{
    private readonly Mock<IContaCorrenteRepository> _repo = new();
    private readonly ObterSaldoHandler _handler;

    public ObterSaldoHandlerTests()
    {
        _handler = new ObterSaldoHandler(_repo.Object);
    }

    [Fact]
    public async Task Handle_ContaValidaEAtiva_RetornaSaldo()
    {
        var cpf = "12345678900";
        var conta = new BankMore.ContaCorrente.Domain.Entities.ContaCorrente
        {
            IdContaCorrente = Guid.NewGuid().ToString(),
            Cpf = cpf,
            Nome = "Teste",
            Numero = 123456,
            Ativo = true
        };
        var saldo = 1000.50m;

        _repo.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);
        _repo.Setup(r => r.ObterSaldo(conta.IdContaCorrente)).ReturnsAsync(saldo);

        var result = await _handler.Handle(new ObterSaldoQuery(cpf), CancellationToken.None);

        Assert.NotNull(result);
        Assert.Equal(conta.Numero, result.NumeroConta);
        Assert.Equal(conta.Nome, result.NomeTitular);
        Assert.Equal(saldo, result.Saldo);
    }

    [Fact]
    public async Task Handle_ContaInexistente_RetornaPlaceholderZero()
    {
        // Contrato atual: handler retorna placeholder zerado (não throw)
        // para o dashboard não quebrar com 500. Pode mudar quando frontend tratar 404.
        var cpf = "12345678900";
        _repo.Setup(r => r.ObterPorCpf(cpf))
             .ReturnsAsync((BankMore.ContaCorrente.Domain.Entities.ContaCorrente?)null);

        var result = await _handler.Handle(new ObterSaldoQuery(cpf), CancellationToken.None);

        Assert.NotNull(result);
        Assert.Equal(0m, result.Saldo);
        Assert.Equal(0, result.NumeroConta);
        _repo.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
    }

    [Fact]
    public async Task Handle_ContaInativa_RetornaPlaceholderZero()
    {
        var cpf = "12345678900";
        var conta = new BankMore.ContaCorrente.Domain.Entities.ContaCorrente
        {
            IdContaCorrente = Guid.NewGuid().ToString(),
            Cpf = cpf,
            Nome = "Teste",
            Numero = 123456,
            Ativo = false
        };
        _repo.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);

        var result = await _handler.Handle(new ObterSaldoQuery(cpf), CancellationToken.None);

        Assert.NotNull(result);
        Assert.Equal(0m, result.Saldo);
        _repo.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
    }
}
