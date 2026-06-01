using Xunit;
using Moq;
using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;

namespace BankMore.ContaCorrente.Application.Tests;

public class ObterExtratoHandlerTests
{
    private readonly Mock<IContaCorrenteRepository> _repo = new();
    private readonly ObterExtratoHandler _handler;

    public ObterExtratoHandlerTests()
    {
        _handler = new ObterExtratoHandler(_repo.Object);
    }

    [Fact]
    public async Task Handle_ContaComMovimentos_RetornaExtratoComCategorias()
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
        var saldo = 1494.00m;
        var movimentos = new List<Movimento>
        {
            new() { DataMovimento = DateTime.UtcNow.AddDays(-3), TipoMovimento = "C", Valor = 1000m, Categoria = "SALDO_INICIAL" },
            new() { DataMovimento = DateTime.UtcNow.AddDays(-2), TipoMovimento = "D", Valor = 500m,  Categoria = "TRANSFERENCIA" },
            new() { DataMovimento = DateTime.UtcNow.AddDays(-2), TipoMovimento = "D", Valor = 4m,    Categoria = "TARIFA" },
            new() { DataMovimento = DateTime.UtcNow.AddDays(-1), TipoMovimento = "C", Valor = 1000m, Categoria = "TRANSFERENCIA" }
        };

        _repo.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);
        _repo.Setup(r => r.ObterSaldo(conta.IdContaCorrente)).ReturnsAsync(saldo);
        _repo.Setup(r => r.ObterMovimentos(conta.IdContaCorrente)).ReturnsAsync(movimentos);

        var result = await _handler.Handle(new ObterExtratoQuery(cpf), CancellationToken.None);

        Assert.NotNull(result);
        Assert.Equal("Teste", result.NomeTitular);
        Assert.Equal(saldo, result.SaldoAtual);
        Assert.Equal(4, result.Movimentos.Count);
        Assert.Contains(result.Movimentos, m => m.Descricao == "Saldo inicial");
        Assert.Contains(result.Movimentos, m => m.Descricao == "Transferência recebida");
        Assert.Contains(result.Movimentos, m => m.Descricao == "Transferência enviada");
        Assert.Contains(result.Movimentos, m => m.Descricao == "Tarifa de transferência");
    }

    [Fact]
    public async Task Handle_ContaInexistente_RetornaExtratoVazio()
    {
        _repo.Setup(r => r.ObterPorCpf(It.IsAny<string>()))
             .ReturnsAsync((BankMore.ContaCorrente.Domain.Entities.ContaCorrente?)null);

        var result = await _handler.Handle(new ObterExtratoQuery("00000000000"), CancellationToken.None);

        Assert.NotNull(result);
        Assert.Empty(result.Movimentos);
        Assert.Equal(0m, result.SaldoAtual);
        _repo.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
        _repo.Verify(r => r.ObterMovimentos(It.IsAny<string>()), Times.Never);
    }
}
