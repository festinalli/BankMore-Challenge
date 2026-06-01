using BankMore.Pix.Domain;
using MediatR;

namespace BankMore.Pix.Application;

/// <summary>Registra uma chave PIX: grava local + propaga pro DICT (bacen-sim).</summary>
public sealed record RegistrarChaveCommand(
    string Cpf, TipoChave Tipo, string ValorChave) : IRequest<RegistrarChaveResult>;

public sealed record RegistrarChaveResult(bool Sucesso, string? Erro, Guid? ChaveId);

public sealed class RegistrarChaveHandler : IRequestHandler<RegistrarChaveCommand, RegistrarChaveResult>
{
    private readonly IPixRepository _repo;
    private readonly IDictClient _dict;

    public RegistrarChaveHandler(IPixRepository repo, IDictClient dict)
    {
        _repo = repo;
        _dict = dict;
    }

    public async Task<RegistrarChaveResult> Handle(RegistrarChaveCommand cmd, CancellationToken ct)
    {
        var idConta = await _repo.ObterIdContaPorCpf(cmd.Cpf, ct);
        if (idConta is null)
            return new RegistrarChaveResult(false, "Conta não encontrada para o CPF", null);

        // EVP é aleatória; demais validam formato mínimo
        var valor = cmd.Tipo == TipoChave.EVP ? Guid.NewGuid().ToString() : cmd.ValorChave;

        var nome = await _repo.ObterNomePorCpf(cmd.Cpf, ct) ?? "";

        // Idempotente: se a chave já existe localmente, ainda assim re-propaga pro DICT.
        // O DICT é a fonte de verdade da resolução; se ele perdeu estado (ex: restart),
        // re-registrar restaura a entrada sem erro. Só rejeita se for de OUTRO titular.
        var existente = await _repo.ObterChaveLocal(valor, ct);
        if (existente is not null)
        {
            if (existente.IdContaCorrente != idConta)
                return new RegistrarChaveResult(false, "Chave pertence a outro titular", null);
            await _dict.RegistrarChave(valor, existente.Tipo.ToString(), cmd.Cpf, nome, ct);
            return new RegistrarChaveResult(true, null, existente.Id);
        }

        var chave = new PixChave
        {
            Tipo = cmd.Tipo, ValorChave = valor, IdContaCorrente = idConta, Status = "ATIVA",
        };
        await _repo.SalvarChave(chave, ct);
        await _dict.RegistrarChave(valor, cmd.Tipo.ToString(), cmd.Cpf, nome, ct);

        return new RegistrarChaveResult(true, null, chave.Id);
    }
}
