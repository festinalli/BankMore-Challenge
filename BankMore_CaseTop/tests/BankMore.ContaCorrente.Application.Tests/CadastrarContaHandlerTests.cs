using Xunit;
using Moq;
using System;
using System.Threading;
using System.Threading.Tasks;
using BankMore.ContaCorrente.Application.Handlers;
using BankMore.ContaCorrente.Domain.Entities;
using BankMore.ContaCorrente.Domain.Interfaces;
using BankMore.ContaCorrente.Application.Services;

namespace BankMore.ContaCorrente.Application.Tests
{
    public class CadastrarContaHandlerTests
    {
        private readonly Mock<IContaCorrenteRepository> _mockRepository;
        private readonly Mock<IPasswordHasher> _mockPasswordHasher;
        private readonly CadastrarContaHandler _handler;

        public CadastrarContaHandlerTests()
        {
            _mockRepository = new Mock<IContaCorrenteRepository>();
            _mockPasswordHasher = new Mock<IPasswordHasher>();
            _mockPasswordHasher.Setup(p => p.HashPassword(It.IsAny<string>(), It.IsAny<string>()))
                               .Returns((string password, string salt) => password + salt); // Mock simples para o teste
            _handler = new CadastrarContaHandler(_mockRepository.Object, _mockPasswordHasher.Object);
        }

        [Fact]
        public async Task Handle_ValidCommand_ReturnsCadastrarContaResponse() 
        {
            // Arrange
            var command = new CadastrarContaCommand("João Silva", "12345678900", "senha123", 100.00m);
            _mockRepository.Setup(r => r.ObterPorCpf(command.Cpf)).ReturnsAsync((BankMore.ContaCorrente.Domain.Entities.ContaCorrente)null);
            _mockRepository.Setup(r => r.Cadastrar(It.IsAny<BankMore.ContaCorrente.Domain.Entities.ContaCorrente>())).ReturnsAsync(Guid.NewGuid().ToString());
            _mockRepository.Setup(r => r.AdicionarMovimento(It.IsAny<Movimento>())).Returns(Task.CompletedTask);

            // Act
            var result = await _handler.Handle(command, CancellationToken.None);

            // Assert
            Assert.NotNull(result);
            Assert.NotEmpty(result.IdContaCorrente);
            Assert.Equal(command.Nome, result.NomeTitular);
            Assert.Equal(command.Cpf, result.Cpf);
            Assert.True(result.NumeroConta > 0);
            _mockRepository.Verify(r => r.Cadastrar(It.IsAny<BankMore.ContaCorrente.Domain.Entities.ContaCorrente>()), Times.Once);
            _mockRepository.Verify(r => r.AdicionarMovimento(It.IsAny<Movimento>()), Times.Once);
        }

        [Fact]
        public async Task Handle_CpfAlreadyExists_ThrowsInvalidOperationException()
        {
            // Arrange
            var command = new CadastrarContaCommand("João Silva", "12345678900", "senha123", 100.00m);
            _mockRepository.Setup(r => r.ObterPorCpf(command.Cpf)).ReturnsAsync(new BankMore.ContaCorrente.Domain.Entities.ContaCorrente { Cpf = command.Cpf });

            // Act & Assert
            await Assert.ThrowsAsync<InvalidOperationException>(
                () => _handler.Handle(command, CancellationToken.None));
            _mockRepository.Verify(r => r.Cadastrar(It.IsAny<BankMore.ContaCorrente.Domain.Entities.ContaCorrente>()), Times.Never);
            _mockRepository.Verify(r => r.AdicionarMovimento(It.IsAny<Movimento>()), Times.Never);
        }

        [Fact]
        public async Task Handle_InvalidCpf_ThrowsArgumentException()
        {
            // Arrange
            var command = new CadastrarContaCommand("João Silva", "123", "senha123", 100.00m);

            // Act & Assert
            await Assert.ThrowsAsync<ArgumentException>(
                () => _handler.Handle(command, CancellationToken.None));
            _mockRepository.Verify(r => r.Cadastrar(It.IsAny<BankMore.ContaCorrente.Domain.Entities.ContaCorrente>()), Times.Never);
            _mockRepository.Verify(r => r.AdicionarMovimento(It.IsAny<Movimento>()), Times.Never);
        }
    }
}
