using BankMore.Pix.Domain;
using MediatR;

namespace BankMore.Pix.Application;

public sealed record QrCodeResult(string Txid, string PayloadEmv, string Tipo, decimal? Valor);

/// <summary>Gera QR estático (chave + valor opcional, reutilizável).</summary>
public sealed record GerarQrEstaticoCommand(
    string Cpf, string Chave, decimal? Valor, string? Descricao) : IRequest<QrCodeResult>;

public sealed class GerarQrEstaticoHandler : IRequestHandler<GerarQrEstaticoCommand, QrCodeResult>
{
    private readonly IPixRepository _repo;
    public GerarQrEstaticoHandler(IPixRepository repo) => _repo = repo;

    public async Task<QrCodeResult> Handle(GerarQrEstaticoCommand cmd, CancellationToken ct)
    {
        var nome = await _repo.ObterNomePorCpf(cmd.Cpf, ct) ?? "BANKMORE";
        var payload = BrCode.GerarEstatico(cmd.Chave, cmd.Valor, nome, "SAO PAULO");

        var qr = new PixQrCode
        {
            Txid = "***", Tipo = TipoQrCode.ESTATICO, Chave = cmd.Chave, Valor = cmd.Valor,
            PayloadEmv = payload, Descricao = cmd.Descricao, Status = "ATIVO",
        };
        // txid "***" não é único; usa um id sintético pra persistência (estático é reutilizável)
        var qrPersist = new PixQrCode
        {
            Id = qr.Id, Txid = "EST" + qr.Id.ToString("N")[..16], Tipo = qr.Tipo, Chave = qr.Chave,
            Valor = qr.Valor, PayloadEmv = payload, Descricao = qr.Descricao, Status = "ATIVO",
        };
        await _repo.SalvarQrCode(qrPersist, ct);
        return new QrCodeResult(qrPersist.Txid, payload, "ESTATICO", cmd.Valor);
    }
}

/// <summary>Gera QR dinâmico / cobrança com vencimento (CoBV). txid único 25 chars.</summary>
public sealed record GerarQrDinamicoCommand(
    string Cpf, string Chave, decimal Valor, string? Descricao, DateTimeOffset? Vencimento) : IRequest<QrCodeResult>;

public sealed class GerarQrDinamicoHandler : IRequestHandler<GerarQrDinamicoCommand, QrCodeResult>
{
    private readonly IPixRepository _repo;
    public GerarQrDinamicoHandler(IPixRepository repo) => _repo = repo;

    public async Task<QrCodeResult> Handle(GerarQrDinamicoCommand cmd, CancellationToken ct)
    {
        var nome = await _repo.ObterNomePorCpf(cmd.Cpf, ct) ?? "BANKMORE";
        var txid = BrCode.GerarTxid();
        // No PIX dinâmico real o campo 26 carrega a URL do payload JWS. Apontamos
        // pro endpoint do próprio PSP que serve o payload (location).
        var urlPayload = $"pix.bankmore.com/qr/v2/{txid}";
        var payload = BrCode.GerarDinamico(urlPayload, nome, "SAO PAULO", txid);

        var tipo = cmd.Vencimento is null ? TipoQrCode.DINAMICO : TipoQrCode.COBV;
        var qr = new PixQrCode
        {
            Txid = txid, Tipo = tipo, Chave = cmd.Chave, Valor = cmd.Valor, PayloadEmv = payload,
            Descricao = cmd.Descricao, Status = "ATIVO", Vencimento = cmd.Vencimento,
        };
        await _repo.SalvarQrCode(qr, ct);
        return new QrCodeResult(txid, payload, tipo.ToString(), cmd.Valor);
    }
}
