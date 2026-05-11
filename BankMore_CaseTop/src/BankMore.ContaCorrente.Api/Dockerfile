FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj", "src/BankMore.ContaCorrente.Api/"]
COPY ["src/BankMore.ContaCorrente.Application/BankMore.ContaCorrente.Application.csproj", "src/BankMore.ContaCorrente.Application/"]
COPY ["src/BankMore.ContaCorrente.Domain/BankMore.ContaCorrente.Domain.csproj", "src/BankMore.ContaCorrente.Domain/"]
COPY ["src/BankMore.ContaCorrente.Infrastructure/BankMore.ContaCorrente.Infrastructure.csproj", "src/BankMore.ContaCorrente.Infrastructure/"]
RUN dotnet restore "src/BankMore.ContaCorrente.Api/BankMore.ContaCorrente.Api.csproj"
COPY . .
WORKDIR "/src/src/BankMore.ContaCorrente.Api"
RUN dotnet build "BankMore.ContaCorrente.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BankMore.ContaCorrente.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "BankMore.ContaCorrente.Api.dll"]
