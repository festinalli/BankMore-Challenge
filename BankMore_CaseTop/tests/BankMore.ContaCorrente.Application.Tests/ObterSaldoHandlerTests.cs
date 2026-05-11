using Xunit;
using Moq;
using System;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;

namespace BankMore.ContaCorrente.Application.Tests
{
    public class ObterSaldoHandlerTests
    {
        private readonly Mock<IContaCorrenteRepository> _mockRepository;
        private readonly ObterSaldoHandler _handler;

        public ObterSaldoHandlerTests()
        {
            _mockRepository = new Mock<IContaCorrenteRepository>();
            _handler = new ObterSaldoHandler(_mockRepository.Object);
        }

        [Fact]
        public async Task Handle_ValidCpf_ReturnsSaldoResponse()
        {
            // Arrange
            var cpf = "12345678900";
            var conta = new BankMore.ContaCorrente.Domain.Entities.ContaCorrente { IdContaCorrente = Guid.NewGuid().ToString(), Cpf = cpf, Nome = "Teste", Numero = 123456, Ativo = true };
            var saldo = 1000.50m;

            _mockRepository.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);
            _mockRepository.Setup(r => r.ObterSaldo(conta.IdContaCorrente)).ReturnsAsync(saldo);

            var query = new ObterSaldoQuery(cpf);

            // Act
            var result = await _handler.Handle(query, CancellationToken.None);

            // Assert
            Assert.NotNull(result);
            Assert.Equal(conta.Numero, result.NumeroConta);
            Assert.Equal(conta.Nome, result.NomeTitular);
            Assert.Equal(saldo, result.Saldo);
            _mockRepository.Verify(r => r.ObterPorCpf(cpf), Times.Once);
            _mockRepository.Verify(r => r.ObterSaldo(conta.IdContaCorrente), Times.Once);
        }

        [Fact]
        public async Task Handle_AccountNotFound_ThrowsException()
        {
            // Arrange
            var cpf = "12345678900";
            _mockRepository.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync((BankMore.ContaCorrente.Domain.Entities.ContaCorrente)null);

            var query = new ObterSaldoQuery(cpf);

            // Act & Assert
            await Assert.ThrowsAsync<Exception>(
                () => _handler.Handle(query, CancellationToken.None));
            _mockRepository.Verify(r => r.ObterPorCpf(cpf), Times.Once);
            _mockRepository.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
        }

        [Fact]
        public async Task Handle_InactiveAccount_ThrowsException()
        {
            // Arrange
            var cpf = "12345678900";
            var conta = new BankMore.ContaCorrente.Domain.Entities.ContaCorrente { IdContaCorrente = Guid.NewGuid().ToString(), Cpf = cpf, Nome = "Teste", Numero = 123456, Ativo = false };

            _mockRepository.Setup(r => r.ObterPorCpf(cpf)).ReturnsAsync(conta);

            var query = new ObterSaldoQuery(cpf);

            // Act & Assert
            await Assert.ThrowsAsync<Exception>(
                () => _handler.Handle(query, CancellationToken.None));
            _mockRepository.Verify(r => r.ObterPorCpf(cpf), Times.Once);
            _mockRepository.Verify(r => r.ObterSaldo(It.IsAny<string>()), Times.Never);
        }
    }
}
