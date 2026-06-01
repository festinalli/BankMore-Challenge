# BankMore.Tarifas.Worker — multi-stage .NET 8
# Build context: raiz do BankMore_CaseTop/
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/BankMore.Tarifas.Worker/BankMore.Tarifas.Worker.csproj src/BankMore.Tarifas.Worker/

RUN dotnet restore src/BankMore.Tarifas.Worker/BankMore.Tarifas.Worker.csproj

COPY src/ src/
RUN dotnet publish src/BankMore.Tarifas.Worker/BankMore.Tarifas.Worker.csproj \
    -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish ./

ENV DOTNET_ENVIRONMENT=Production

ENTRYPOINT ["dotnet", "BankMore.Tarifas.Worker.dll"]
