using BankMore.Tarifas.Worker.Handlers;
using KafkaFlow;
using KafkaFlow.Serializer;
using Microsoft.Extensions.Hosting;

var builder = Host.CreateApplicationBuilder(args);

var kafkaBroker = builder.Configuration.GetValue<string>("Kafka:Broker")
    ?? Environment.GetEnvironmentVariable("KAFKA_BROKER")
    ?? "localhost:9092";

// Postgres connection string fica em IConfiguration — TarifaConsumer puxa via IConfiguration.
// Schema é gerenciado pelo init.sql do Postgres; Worker não cria tabela.

builder.Services.AddKafka(kafka => kafka
    .UseConsoleLog()
    .AddCluster(cluster => cluster
        .WithBrokers(new[] { kafkaBroker })
        .AddConsumer(consumer => consumer
            .Topic("transferencia.aprovada")
            .WithGroupId("tarifas-worker")
            .WithBufferSize(100)
            .WithWorkersCount(2)
            .WithAutoOffsetReset(AutoOffsetReset.Earliest)
            .AddMiddlewares(middlewares => middlewares
                .AddSingleTypeDeserializer<TransferenciaAprovadaMessage, NewtonsoftJsonDeserializer>()
                .AddTypedHandlers(handlers => handlers.AddHandler<TarifaConsumer>())
            )
        )
    )
);

var host = builder.Build();

var kafkaBus = host.Services.CreateKafkaBus();
await kafkaBus.StartAsync();

await host.RunAsync();
