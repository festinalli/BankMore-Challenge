FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["src/BankMore.Tarifas.Worker/BankMore.Tarifas.Worker.csproj", "src/BankMore.Tarifas.Worker/"]
RUN dotnet restore "src/BankMore.Tarifas.Worker/BankMore.Tarifas.Worker.csproj"
COPY . .
WORKDIR "/src/src/BankMore.Tarifas.Worker"
RUN dotnet build "BankMore.Tarifas.Worker.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BankMore.Tarifas.Worker.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "BankMore.Tarifas.Worker.dll"]
