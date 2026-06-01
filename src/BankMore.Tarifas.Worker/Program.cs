using BankMore.Tarifas.Worker.Handlers;
using BankMore.Tarifas.Worker.Services;
using KafkaFlow;
using KafkaFlow.Serializer;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Prometheus;
using StackExchange.Redis;

var builder = Host.CreateApplicationBuilder(args);

var kafkaBroker = builder.Configuration.GetValue<string>("Kafka:Broker")
    ?? Environment.GetEnvironmentVariable("KAFKA_BROKER")
    ?? "localhost:9092";

var redisConn = builder.Configuration.GetValue<string>("Redis:Connection")
    ?? Environment.GetEnvironmentVariable("REDIS_CONNECTION")
    ?? "localhost:6379";

// Postgres connection string fica em IConfiguration — TarifaConsumer puxa via IConfiguration.
// Schema é gerenciado pelo init.sql do Postgres; Worker não cria tabela.

// Sprint 4.B: feature store em Redis
builder.Services.AddSingleton<IConnectionMultiplexer>(
    _ => ConnectionMultiplexer.Connect(redisConn));
builder.Services.AddSingleton<FeatureStore>();

builder.Services.AddKafka(kafka => kafka
    .UseConsoleLog()
    .AddCluster(cluster => cluster
        .WithBrokers(new[] { kafkaBroker })
        // Consumer 1: efetivação de transferências aprovadas (debita/credita/tarifa)
        .AddConsumer(consumer => consumer
            .Topic("transferencia.aprovada")
            .WithGroupId("tarifas-worker-aprovadas")
            .WithBufferSize(100)
            .WithWorkersCount(2)
            .WithAutoOffsetReset(AutoOffsetReset.Earliest)
            .AddMiddlewares(middlewares => middlewares
                .AddSingleTypeDeserializer<TransferenciaAprovadaMessage, NewtonsoftJsonDeserializer>()
                .AddTypedHandlers(handlers => handlers.AddHandler<TarifaConsumer>())
            )
        )
        // Consumer 2: rejeições — apenas atualiza status na tabela transferencia
        .AddConsumer(consumer => consumer
            .Topic("transferencia.rejeitada")
            .WithGroupId("tarifas-worker-rejeitadas")
            .WithBufferSize(100)
            .WithWorkersCount(1)
            .WithAutoOffsetReset(AutoOffsetReset.Earliest)
            .AddMiddlewares(middlewares => middlewares
                .AddSingleTypeDeserializer<TransferenciaRejeitadaMessage, NewtonsoftJsonDeserializer>()
                .AddTypedHandlers(handlers => handlers.AddHandler<RejeicaoConsumer>())
            )
        )
        // Consumer 3 (Sprint 10.A): análise pós-liquidação do PIX — enriquece feature
        // store + alerta de burst. Não bloqueia (o PIX já liquidou inline).
        .AddConsumer(consumer => consumer
            .Topic("pix.liquidada")
            .WithGroupId("tarifas-worker-pix-pos")
            .WithBufferSize(100)
            .WithWorkersCount(2)
            .WithAutoOffsetReset(AutoOffsetReset.Earliest)
            .AddMiddlewares(middlewares => middlewares
                .AddSingleTypeDeserializer<PixLiquidadaMessage, NewtonsoftJsonDeserializer>()
                .AddTypedHandlers(handlers => handlers.AddHandler<PixLiquidadoConsumer>())
            )
        )
    )
);

var host = builder.Build();

// Prometheus: MetricServer standalone (Worker SDK não tem pipeline HTTP).
// Usa HttpListener interno do .NET — expõe /metrics na porta 9102.
// prometheus-net registra automaticamente métricas de runtime (CLR, GC, threads).
var metricsPort = int.Parse(Environment.GetEnvironmentVariable("METRICS_PORT") ?? "9102");
var metricsServer = new MetricServer(hostname: "+", port: metricsPort);
metricsServer.Start();

var kafkaBus = host.Services.CreateKafkaBus();
await kafkaBus.StartAsync();

await host.RunAsync();
