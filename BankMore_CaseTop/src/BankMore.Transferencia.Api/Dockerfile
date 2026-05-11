FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["src/BankMore.Transferencia.Api/BankMore.Transferencia.Api.csproj", "src/BankMore.Transferencia.Api/"]
COPY ["src/BankMore.Transferencia.Application/BankMore.Transferencia.Application.csproj", "src/BankMore.Transferencia.Application/"]
COPY ["src/BankMore.Transferencia.Domain/BankMore.Transferencia.Domain.csproj", "src/BankMore.Transferencia.Domain/"]
COPY ["src/BankMore.Transferencia.Infrastructure/BankMore.Transferencia.Infrastructure.csproj", "src/BankMore.Transferencia.Infrastructure/"]
RUN dotnet restore "src/BankMore.Transferencia.Api/BankMore.Transferencia.Api.csproj"
COPY . .
WORKDIR "/src/src/BankMore.Transferencia.Api"
RUN dotnet build "BankMore.Transferencia.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BankMore.Transferencia.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "BankMore.Transferencia.Api.dll"]
