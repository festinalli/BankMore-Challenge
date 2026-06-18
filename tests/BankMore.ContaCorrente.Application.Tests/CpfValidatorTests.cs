using BankMore.ContaCorrente.Application.Services;
using Xunit;

namespace BankMore.ContaCorrente.Application.Tests;

/// <summary>Testes do CpfValidator — dígitos verificadores (algoritmo Receita Federal).</summary>
public class CpfValidatorTests
{
    [Theory]
    [InlineData("11144477735")]   // Alice (seed)
    [InlineData("52998224725")]   // Bob (seed)
    [InlineData("12345678909")]   // Carol (seed)
    [InlineData("111.444.777-35")] // com máscara — validador normaliza
    public void IsValid_CpfComDvCorreto_True(string cpf)
        => Assert.True(CpfValidator.IsValid(cpf));

    [Theory]
    [InlineData("12345678900")]   // DV incorreto (o do teste antigo, que falhava)
    [InlineData("11144477736")]   // último dígito trocado
    [InlineData("00000000000")]   // todos iguais
    [InlineData("11111111111")]   // todos iguais
    [InlineData("123")]           // curto
    [InlineData("123456789012")]  // longo
    [InlineData("1114447773a")]   // com letra
    [InlineData("")]              // vazio
    [InlineData("   ")]           // só espaço
    [InlineData(null)]            // nulo
    public void IsValid_CpfInvalido_False(string? cpf)
        => Assert.False(CpfValidator.IsValid(cpf));
}
