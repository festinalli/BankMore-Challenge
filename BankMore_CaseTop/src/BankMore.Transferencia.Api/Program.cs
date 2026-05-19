using BankMore.Transferencia.Api.Middleware;
using BankMore.Transferencia.Api.Services;
using Confluent.SchemaRegistry;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Prometheus;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using System.Text;
using System.Text.Json.Serialization;
using MediatR;
using BankMore.Transferencia.Application.Handlers;

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("ASPNETCORE_URLS") ?? "http://localhost:5001");

builder.Services
    .AddControllers()
    .AddJsonOptions(o => o.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter()));
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "BankMore Transferência API", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header. Ex: \"Authorization: Bearer {token}\"",
        Name = "Authorization",
        In = ParameterLocation.Header,
        Type = SecuritySchemeType.ApiKey,
        Scheme = "Bearer"
    });
    c.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme { Reference = new OpenApiReference { Type = ReferenceType.SecurityScheme, Id = "Bearer" } },
            new string[] {}
        }
    });
});

var jwtKey = builder.Configuration["Jwt:Key"]
    ?? Environment.GetEnvironmentVariable("JWT_KEY")
    ?? throw new InvalidOperationException("Jwt:Key não configurada — defina via env var JWT_KEY ou appsettings");

if (jwtKey.Length < 32)
    throw new InvalidOperationException("Jwt:Key deve ter pelo menos 32 caracteres (256 bits)");

var keyBytes = Encoding.UTF8.GetBytes(jwtKey);

builder.Services.AddAuthentication(x =>
{
    x.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    x.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(x =>
{
    x.RequireHttpsMetadata = false;
    x.SaveToken = true;
    x.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuerSigningKey = true,
        IssuerSigningKey = new SymmetricSecurityKey(keyBytes),
        ValidateIssuer = false,
        ValidateAudience = false,
        ValidateLifetime = true,   // antes estava false — corrigido
        ClockSkew = TimeSpan.Zero
    };
});

// Sprint 5.B — KafkaFlow producer removido. Publicação no Kafka é feita pelo
// OutboxRelayHostedService a partir da tabela transferencia_outbox.

builder.Services.AddMediatR(cfg => cfg.RegisterServicesFromAssembly(typeof(EfetuarTransferenciaHandler).Assembly));

// --- 5b. Repositório (Transferencia.Infrastructure) ---
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? throw new InvalidOperationException("ConnectionStrings:DefaultConnection ausente");
builder.Services.AddSingleton<BankMore.Transferencia.Domain.ITransferenciaRepository>(
    _ => new BankMore.Transferencia.Infrastructure.TransferenciaRepository(connectionString));

// Sprint 6.B — Schema Registry client + AvroSerdes pra OutboxRelay serializar
// Avro binário em transferencia.solicitada. Fallback JSON UTF-8 se SR cair
// (resilience: OutboxRelay detecta avroSerdes==null e usa JSON).
var schemaRegistryUrl = builder.Configuration["SchemaRegistry:Url"]
    ?? Environment.GetEnvironmentVariable("SCHEMA_REGISTRY_URL")
    ?? "http://schema-registry:8081";
builder.Services.AddSingleton<ISchemaRegistryClient>(
    _ => new CachedSchemaRegistryClient(new SchemaRegistryConfig { Url = schemaRegistryUrl }));
builder.Services.AddSingleton<AvroSerdes>();

// Sprint 5.B — Outbox relay como BackgroundService dentro da API.
builder.Services.AddHostedService<OutboxRelayHostedService>();

builder.Services.AddCors(options =>
    options.AddPolicy("DefaultPolicy", p =>
        p.WithOrigins("http://localhost:4200").AllowAnyMethod().AllowAnyHeader()));

var app = builder.Build();

app.UseMiddleware<ExceptionMiddleware>();
app.UseHttpMetrics();
app.MapMetrics("/metrics");
app.UseSwagger();
app.UseSwaggerUI(c => c.SwaggerEndpoint("/swagger/v1/swagger.json", "BankMore Transferência API v1"));
app.UseCors("DefaultPolicy");
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

app.Run();
