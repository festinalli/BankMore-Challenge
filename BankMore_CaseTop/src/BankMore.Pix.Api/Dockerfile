# BankMore.Pix.Api — bounded context PIX — multi-stage .NET 8
# Build context: raiz do BankMore_CaseTop/
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/BankMore.Pix.Api/BankMore.Pix.Api.csproj                       src/BankMore.Pix.Api/
COPY src/BankMore.Pix.Application/BankMore.Pix.Application.csproj       src/BankMore.Pix.Application/
COPY src/BankMore.Pix.Domain/BankMore.Pix.Domain.csproj                 src/BankMore.Pix.Domain/
COPY src/BankMore.Pix.Infrastructure/BankMore.Pix.Infrastructure.csproj src/BankMore.Pix.Infrastructure/

RUN dotnet restore src/BankMore.Pix.Api/BankMore.Pix.Api.csproj

COPY src/BankMore.Pix.Api/          src/BankMore.Pix.Api/
COPY src/BankMore.Pix.Application/  src/BankMore.Pix.Application/
COPY src/BankMore.Pix.Domain/       src/BankMore.Pix.Domain/
COPY src/BankMore.Pix.Infrastructure/ src/BankMore.Pix.Infrastructure/

RUN dotnet publish src/BankMore.Pix.Api/BankMore.Pix.Api.csproj \
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

ENTRYPOINT ["dotnet", "BankMore.Pix.Api.dll"]
