# BankMore.ContaCorrente.Api — multi-stage .NET 8
# Build context: raiz do BankMore_CaseTop/
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj             src/BankMore.ContaCorrente.Api/
COPY src/BankMore.ContaCorrente.Application/BankMore.ContaCorrente.Application.csproj src/BankMore.ContaCorrente.Application/
COPY src/BankMore.ContaCorrente.Domain/BankMore.ContaCorrente.Domain.csproj         src/BankMore.ContaCorrente.Domain/
COPY src/BankMore.ContaCorrente.Infrastructure/BankMore.ContaCorrente.Infrastructure.csproj src/BankMore.ContaCorrente.Infrastructure/

RUN dotnet restore src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj

COPY src/ src/
RUN dotnet publish src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj \
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

ENTRYPOINT ["dotnet", "BankMore.ContaCorrente.Api.dll"]
