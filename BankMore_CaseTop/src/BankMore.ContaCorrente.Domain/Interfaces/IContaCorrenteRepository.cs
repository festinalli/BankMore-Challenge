using System.Threading.Tasks;
using BankMore.ContaCorrente.Domain.Entities;

namespace BankMore.ContaCorrente.Domain.Interfaces
{
    public interface IContaCorrenteRepository
    {
        Task<Entities.ContaCorrente?> ObterPorCpf(string cpf);
        Task<Entities.ContaCorrente?> ObterPorNumero(int numero);
        Task<Entities.ContaCorrente?> ObterPorId(string id);
        Task<string> Cadastrar(Entities.ContaCorrente conta);
        Task Inativar(string id);
        Task AdicionarMovimento(Movimento movimento);
        Task<decimal> ObterSaldo(string idContaCorrente);
        Task<IEnumerable<Movimento>> ObterMovimentos(string idContaCorrente);
        Task<IEnumerable<Tarifa>> ObterTarifas(int numeroConta);
        Task<bool> ExisteChaveIdempotencia(string chave);
        Task SalvarIdempotencia(Idempotencia idempotencia);
    }
}
