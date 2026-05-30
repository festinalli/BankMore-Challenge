# BankMore.BacenSim — simulador BACEN (DICT + SPI) — multi-stage .NET 8
# Build context: raiz do BankMore_CaseTop/
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/BankMore.BacenSim/BankMore.BacenSim.csproj src/BankMore.BacenSim/
RUN dotnet restore src/BankMore.BacenSim/BankMore.BacenSim.csproj

COPY src/BankMore.BacenSim/ src/BankMore.BacenSim/
RUN dotnet publish src/BankMore.BacenSim/BankMore.BacenSim.csproj \
    -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/publish ./

EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -fsS http://localhost:8080/health || exit 1

ENTRYPOINT ["dotnet", "BankMore.BacenSim.dll"]
