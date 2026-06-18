using BankMore.Tarifas.Worker.Handlers;
using BankMore.Tarifas.Worker.Services;
using Dapper;
using KafkaFlow;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Npgsql;
using StackExchange.Redis;
using Testcontainers.PostgreSql;
using Testcontainers.Redis;
using Xunit;

namespace BankMore.Tarifas.Worker.Tests;

/// <summary>
/// Containers efêmeros (Postgres + Redis) compartilhados pela classe. Carrega o schema
/// real (infra/db/init.sql) — é o SQL que roda em produção.
/// </summary>
public sealed class DbFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _pg = new PostgreSqlBuilder()
        .WithImage("postgres:16-alpine").Build();
    private readonly RedisContainer _redis = new RedisBuilder()
        .WithImage("redis:7-alpine").Build();

    public string ConnString => _pg.GetConnectionString();
    public FeatureStore FeatureStore { get; private set; } = null!;
    public IConfiguration Config { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        await _pg.StartAsync();
        await _redis.StartAsync();

        var initSql = await File.ReadAllTextAsync(LocalizarInitSql());
        await using var conn = new NpgsqlConnection(ConnString);
        await conn.OpenAsync();
        await conn.ExecuteAsync(initSql);

        var mux = await ConnectionMultiplexer.ConnectAsync(_redis.GetConnectionString());
        FeatureStore = new FeatureStore(mux, NullLogger<FeatureStore>.Instance);
        Config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["ConnectionStrings:DefaultConnection"] = ConnString })
            .Build();
    }

    public async Task DisposeAsync()
    {
        await _pg.DisposeAsync();
        await _redis.DisposeAsync();
    }

    private static string LocalizarInitSql()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "infra", "db", "init.sql")))
            dir = dir.Parent;
        return Path.Combine(dir!.FullName, "infra", "db", "init.sql");
    }
}

public class TarifaConsumerTests : IClassFixture<DbFixture>
{
    private readonly DbFixture _fx;
    private readonly TarifaConsumer _sut;
    private static int _seq;

    public TarifaConsumerTests(DbFixture fx)
    {
        _fx = fx;
        _sut = new TarifaConsumer(_fx.Config, NullLogger<TarifaConsumer>.Instance, _fx.FeatureStore);
    }

    [Fact]
    public async Task ComSaldo_EfetivaEMovimenta()
    {
        var (origem, destino, transfId) = await Cenario(saldoOrigem: 1000m);
        var msg = Mensagem(transfId, origem, destino, valor: 100m, taxa: 4m, tipo: "TED");

        await _sut.Handle(Ctx(), msg);

        Assert.Equal("EFETIVADA", await Status(transfId));
        // origem debitada de valor + taxa; destino creditado do valor
        Assert.Equal(1000m - 104m, await Saldo(origem.id));
        Assert.Equal(100m, await Saldo(destino.id));
        // movimentos: D valor + D tarifa na origem, C valor no destino
        Assert.Equal(2, await ContaMovimentos(origem.id, "D"));
        Assert.Equal(1, await ContaMovimentos(destino.id, "C"));
        Assert.Equal(1, await CountIdempotencia(transfId));
        Assert.Equal(1, await CountTarifa(transfId)); // auditoria da tarifa
    }

    [Fact]
    public async Task SemSaldo_Compensa_SemDebitar()
    {
        var (origem, destino, transfId) = await Cenario(saldoOrigem: 50m);
        var msg = Mensagem(transfId, origem, destino, valor: 100m, taxa: 4m, tipo: "TED");

        await _sut.Handle(Ctx(), msg);

        Assert.Equal("COMPENSADA", await Status(transfId));
        Assert.Equal("SALDO_INSUFICIENTE", await Motivo(transfId));
        // nada foi debitado/creditado — só o crédito inicial de seed na origem
        Assert.Equal(50m, await Saldo(origem.id));
        Assert.Equal(0m, await Saldo(destino.id));
        Assert.Equal(0, await ContaMovimentos(origem.id, "D"));
        Assert.Equal(1, await CountIdempotencia(transfId)); // registra p/ não reprocessar
    }

    [Fact]
    public async Task Replay_NaoDuplicaDebito()
    {
        var (origem, destino, transfId) = await Cenario(saldoOrigem: 1000m);
        var msg = Mensagem(transfId, origem, destino, valor: 100m, taxa: 4m, tipo: "TED");

        await _sut.Handle(Ctx(), msg);          // 1ª vez: efetiva
        var saldoApos1 = await Saldo(origem.id);
        var movsApos1 = await ContaMovimentos(origem.id, "D");

        await _sut.Handle(Ctx(), msg);          // replay do MESMO id: idempotente

        Assert.Equal(saldoApos1, await Saldo(origem.id));        // saldo não mudou
        Assert.Equal(movsApos1, await ContaMovimentos(origem.id, "D")); // sem débito novo
        Assert.Equal("EFETIVADA", await Status(transfId));
    }

    // ---- helpers ----
    private static IMessageContext Ctx() => new Mock<IMessageContext>().Object;

    private static TransferenciaAprovadaMessage Mensagem(
        string id, (string id, string cpf, int num) o, (string id, string cpf, int num) d,
        decimal valor, decimal taxa, string tipo) => new()
    {
        Id = id, CorrelationId = "corr-" + id, CpfOrigem = o.cpf, CpfDestino = d.cpf,
        Valor = valor, Taxa = taxa, Tipo = tipo, Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
    };

    /// <summary>Cria 2 contas, credita o saldo da origem e insere a transferência APROVADA.</summary>
    private async Task<((string id, string cpf, int num) origem, (string id, string cpf, int num) destino, string transfId)> Cenario(decimal saldoOrigem)
    {
        var n = Interlocked.Increment(ref _seq);
        var origem = (id: $"o{n:000}", cpf: $"CPFO{n:000}", num: 100000 + n);
        var destino = (id: $"d{n:000}", cpf: $"CPFD{n:000}", num: 200000 + n);
        var transfId = $"t{n:000}";

        await using var c = new NpgsqlConnection(_fx.ConnString);
        await c.OpenAsync();
        foreach (var x in new[] { origem, destino })
            await c.ExecuteAsync(
                "INSERT INTO contacorrente (idcontacorrente,numero,nome,cpf,senha,salt) VALUES (@id,@num,'Teste',@cpf,'x','x')",
                new { x.id, x.num, x.cpf });
        if (saldoOrigem > 0)
            await c.ExecuteAsync(
                "INSERT INTO movimento (idmovimento,idcontacorrente,numeroconta,tipomovimento,valor,categoria) VALUES (@m,@id,@num,'C',@v,'SEED')",
                new { m = "seed" + transfId, origem.id, origem.num, v = saldoOrigem });
        await c.ExecuteAsync(
            "INSERT INTO transferencia (id,correlation_id,cpf_origem,cpf_destino,valor,tipo,status) VALUES (@id,@corr,@o,@d,100,'TED','APROVADA')",
            new { id = transfId, corr = "corr-" + transfId, o = origem.cpf, d = destino.cpf });
        return (origem, destino, transfId);
    }

    private async Task<T> Q<T>(string sql, object p)
    {
        await using var c = new NpgsqlConnection(_fx.ConnString);
        await c.OpenAsync();
        return await c.ExecuteScalarAsync<T>(sql, p);
    }
    private Task<string> Status(string id) => Q<string>("SELECT status FROM transferencia WHERE id=@id", new { id });
    private Task<string?> Motivo(string id) => Q<string?>("SELECT motivo FROM transferencia WHERE id=@id", new { id });
    private Task<decimal> Saldo(string idconta) => Q<decimal>(
        "SELECT COALESCE(SUM(CASE WHEN tipomovimento='C' THEN valor ELSE -valor END),0) FROM movimento WHERE idcontacorrente=@id", new { id = idconta });
    private Task<int> ContaMovimentos(string idconta, string tipo) => Q<int>(
        "SELECT COUNT(1) FROM movimento WHERE idcontacorrente=@id AND tipomovimento=@t AND categoria<>'SEED'", new { id = idconta, t = tipo });
    private Task<int> CountIdempotencia(string id) => Q<int>("SELECT COUNT(1) FROM idempotencia WHERE chave_idempotencia=@id", new { id });
    private Task<int> CountTarifa(string id) => Q<int>("SELECT COUNT(1) FROM tarifa WHERE transferencia_id=@id", new { id });
}
