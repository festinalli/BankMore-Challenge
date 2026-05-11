using Xunit;
using Moq;
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;
using BankMore.ContaCorrente.Application.Models;
using Microsoft.Extensions.Configuration;

namespace BankMore.ContaCorrente.Application.Tests
{
    public class ObterExtratoHandlerTests
    {
        private readonly Mock<IContaCorrenteRepository> _mockRepository;
        private readonly Mock<Microsoft.Extensions.Configuration.IConfiguration> _mockConfiguration;
        private readonly ObterExtratoHandler _handler;

        public ObterExtratoHandlerTests()
        {
            _mockRepository = new Mock<IContaCorrenteRepository>();
            _mockConfiguration = new Mock<Microsoft.Extensions.Configuration.IConfiguration>();
            _mockConfiguration.Setup(c => c.GetConnectionString("DefaultConnection")).Returns("DataSource=:memory:");
            _handler = new ObterExtratoHandler(_mockConfiguration.Object, _mockRepository.Object);
        }

        [Fact]
        public async Task Handle_ValidCpfWithMovementsAndTariffs_ReturnsExtratoResponse()
        {
            // Arrange
            var cpf = "12345678900";
            var conta = new BankMore.ContaCorrente.Domain.Entities.ContaCorrente { IdContaCorrente = Guid.NewGuid().ToString(), Cpf = cpf, Nome = "Teste", Numero = 123456, Ativo = true };
            var saldo = 1500.00m;
            var movements = new List<Movimento>
            {
                new Movimento { IdMovimento = Guid.NewGuid().ToString(), IdContaCorrente = conta.IdContaCorrente, NumeroConta = conta.Numero, DataMovimento = DateTime.Now.AddDays(-1).ToString("yyyy-MM-dd HH:mm:ss"), TipoMovimento = "C", Valor = 1000.00m },
                new Movimento { IdMovimento = Guid.NewGuid().ToString(), IdContaCorrente = conta.IdContaCorrente, NumeroConta = conta.Numero, DataMovimento = DateTime.Now.AddDays(-2).ToString("yyyy-MM-dd HH:mm:ss"), TipoMovimento = "D", Valor = 500.00m }
            };
            var tariffs = new List<Tarifa>
            {
                new Tarifa { Id = Guid.NewGuid().ToString(), NumeroConta = conta.Numero, Valor = 2.00m, DataProcessamento = DateTime.Now.AddDays(-3).ToString("yyyy-MM-dd HH:mm:ss") }
            };

            _mockRepository.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);
            _mockRepository.Setup(r => r.ObterSaldo(conta.IdContaCorrente)).ReturnsAsync(saldo);
            _mockRepository.Setup(r => r.ObterMovimentos(conta.IdContaCorrente)).ReturnsAsync(movements);
            _mockRepository.Setup(r => r.ObterTarifas(conta.Numero)).ReturnsAsync(tariffs);

            var query = new ObterExtratoQuery(cpf);

            // Act
            var result = await _handler.Handle(query, CancellationToken.None);

            // Assert
            Assert.NotNull(result);
            Assert.Equal(conta.Nome, result.NomeTitular);
            Assert.Equal(saldo, result.SaldoAtual);
            Assert.Equal(3, result.Movimentos.Count);
            Assert.Contains(result.Movimentos, m => m.Descricao == "Transferência Recebida");
            Assert.Contains(result.Movimentos, m => m.Descricao == "Transferência Enviada");
            Assert.Contains(result.Movimentos, m => m.Tipo == "Tarifa");
            _mockRepository.Verify(r => r.ObterPorCpf(cpf), Times.Once);
            _mockRepository.Verify(r => r.ObterSaldo(conta.IdContaCorrente), Times.Once);
            _mockRepository.Verify(r => r.ObterMovimentos(conta.IdContaCorrente), Times.Once);
            _mockRepository.Verify(r => r.ObterTarifas(conta.Numero), Times.Once);
        }

        [Fact]
        public async Task Handle_AccountNotFound_ThrowsException()
        {
            // Arrange
            var cpf = "12345678900";
            _mockRepository.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync((BankMore.ContaCorrente.Domain.Entities.ContaCorrente)null);

            var query = new ObterExtratoQuery(cpf);

            // Act & Assert
            var result = await _handler.Handle(query, CancellationToken.None);
            Assert.NotNull(result);
            Assert.Null(result.NomeTitular);
            Assert.Equal(0.0m, result.SaldoAtual);
            Assert.Empty(result.Movimentos);
            _mockRepository.Verify(r => r.ObterPorCpf(cpf), Times.Once);
            _mockRepository.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
            _mockRepository.Verify(r => r.ObterMovimentos(It.IsAny<string>()), Times.Never);
            _mockRepository.Verify(r => r.ObterTarifas(It.IsAny<int>()), Times.Never);
        }
    }
}
