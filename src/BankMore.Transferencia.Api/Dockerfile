# BankMore.Transferencia.Api — multi-stage .NET 8
# Build context: raiz do BankMore_CaseTop/
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/BankMore.Transferencia.Api/BankMore.Transferencia.Api.csproj                       src/BankMore.Transferencia.Api/
COPY src/BankMore.Transferencia.Application/BankMore.Transferencia.Application.csproj       src/BankMore.Transferencia.Application/
COPY src/BankMore.Transferencia.Domain/BankMore.Transferencia.Domain.csproj                 src/BankMore.Transferencia.Domain/
COPY src/BankMore.Transferencia.Infrastructure/BankMore.Transferencia.Infrastructure.csproj src/BankMore.Transferencia.Infrastructure/

RUN dotnet restore src/BankMore.Transferencia.Api/BankMore.Transferencia.Api.csproj

COPY src/ src/
RUN dotnet publish src/BankMore.Transferencia.Api/BankMore.Transferencia.Api.csproj \
    -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/publish ./

EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=20s \
    CMD curl -fsS http://localhost:8080/swagger/v1/swagger.json || exit 1

ENTRYPOINT ["dotnet", "BankMore.Transferencia.Api.dll"]
