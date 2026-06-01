using System.Text;
using System.Text.Json.Serialization;
using BankMore.Pix.Application;
using BankMore.Pix.Domain;
using BankMore.Pix.Infrastructure;
using BankMore.Pix.Api.Services;
using MediatR;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using Prometheus;

// ============================================================================
// BankMore.Pix.Api — bounded context PIX (Sprint 8)
// Pagamento por chave, QR Code (BR Code EMVCo), MED, PIX Automático, NFC, Open Finance.
// Liquidação via bacen-sim (DICT + SPI/ISO 20022).
// ============================================================================

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("ASPNETCORE_URLS") ?? "http://+:8080");

builder.Services
    .AddControllers()
    .AddJsonOptions(o => o.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter()));
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "BankMore PIX API", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT. Ex: \"Authorization: Bearer {token}\"",
        Name = "Authorization", In = ParameterLocation.Header,
        Type = SecuritySchemeType.ApiKey, Scheme = "Bearer"
    });
    c.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        { new OpenApiSecurityScheme { Reference = new OpenApiReference { Type = ReferenceType.SecurityScheme, Id = "Bearer" } }, Array.Empty<string>() }
    });
});

// JWT (mesmo segredo compartilhado do ContaCorrente)
var jwtKey = builder.Configuration["Jwt:Key"]
    ?? Environment.GetEnvironmentVariable("JWT_KEY")
    ?? throw new InvalidOperationException("JWT_KEY não configurada");
if (jwtKey.Length < 32) throw new InvalidOperationException("JWT_KEY < 32 chars");
var keyBytes = Encoding.UTF8.GetBytes(jwtKey);

builder.Services.AddAuthentication(x =>
{
    x.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    x.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
}).AddJwtBearer(x =>
{
    x.RequireHttpsMetadata = false;
    x.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuerSigningKey = true,
        IssuerSigningKey = new SymmetricSecurityKey(keyBytes),
        ValidateIssuer = false, ValidateAudience = false,
        ValidateLifetime = true, ClockSkew = TimeSpan.Zero
    };
});

builder.Services.AddMediatR(cfg => cfg.RegisterServicesFromAssembly(typeof(IniciarPagamentoHandler).Assembly));

// Repositório
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? throw new InvalidOperationException("ConnectionStrings:DefaultConnection ausente");
builder.Services.AddSingleton<IPixRepository>(_ => new PixRepository(connectionString));

// Clients HTTP do bacen-sim (DICT + SPI)
var bacenUrl = builder.Configuration["BacenSim:Url"]
    ?? Environment.GetEnvironmentVariable("BACEN_SIM_URL") ?? "http://bacen-sim:8080";
builder.Services.AddHttpClient<IDictClient, DictClient>(c => c.BaseAddress = new Uri(bacenUrl));
builder.Services.AddHttpClient<ISpiClient, SpiClient>(c => c.BaseAddress = new Uri(bacenUrl));

// Sprint 9 — antifraude inline (scoring síncrono no fraud-ml antes da liquidação)
var fraudeUrl = builder.Configuration["Fraude:Url"]
    ?? Environment.GetEnvironmentVariable("FRAUDE_ML_URL") ?? "http://fraud-ml:5003";
builder.Services.AddHttpClient<IFraudeClient, FraudeClient>(c =>
{
    c.BaseAddress = new Uri(fraudeUrl);
    c.Timeout = TimeSpan.FromSeconds(2);  // PIX é <10s; scoring não pode pendurar
});
var fraudeHabilitado = bool.Parse(builder.Configuration["Fraude:Habilitado"]
    ?? Environment.GetEnvironmentVariable("FRAUDE_HABILITADO") ?? "true");
var fraudeThreshold = double.Parse(builder.Configuration["Fraude:Threshold"]
    ?? Environment.GetEnvironmentVariable("FRAUDE_THRESHOLD") ?? "0.95",
    System.Globalization.CultureInfo.InvariantCulture);
builder.Services.AddSingleton(new PixFraudeConfig(fraudeHabilitado, fraudeThreshold));

// Sprint 10.A — publisher de pix.liquidada pra análise pós-liquidação em streaming
var kafkaBroker = builder.Configuration["Kafka:Broker"]
    ?? Environment.GetEnvironmentVariable("KAFKA_BROKER") ?? "kafka:29092";
builder.Services.AddSingleton<IPixEventPublisher>(sp =>
    new PixEventPublisher(kafkaBroker, sp.GetRequiredService<ILogger<PixEventPublisher>>()));

builder.Services.AddScoped<PixLiquidacaoService>();

// Sprint 8.E — scheduler de recorrência do PIX Automático
builder.Services.AddHostedService<RecorrenciaScheduler>();

builder.Services.AddCors(o => o.AddPolicy("Default", p =>
    p.WithOrigins("http://localhost:4200").AllowAnyMethod().AllowAnyHeader()));

var app = builder.Build();
app.UseHttpMetrics();
app.MapMetrics("/metrics");
app.UseSwagger();
app.UseSwaggerUI(c => c.SwaggerEndpoint("/swagger/v1/swagger.json", "BankMore PIX API v1"));
app.UseCors("Default");
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

app.Run();
