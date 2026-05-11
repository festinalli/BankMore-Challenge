# BankMore Case Top — Makefile

COMPOSE := docker compose --env-file .env -f infra/compose/docker-compose.yml
DOTNET  := dotnet
PSQL    := docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db

.PHONY: help env up down ps logs reset psql topics seed \
        run-contacorrente run-transferencia run-worker run-approver \
        build test e2e

help:
	@echo "BankMore Case Top — targets:"
	@echo "  make env                Cria .env a partir de .env.example (se ainda não existir)"
	@echo "  make up                 Sobe TUDO (infra + APIs + worker + auto-approver)"
	@echo "  make down               Derruba tudo (mantém volumes)"
	@echo "  make reset              Derruba + apaga volumes (zera o banco)"
	@echo "  make ps                 Status dos containers"
	@echo "  make logs               Logs em tempo real"
	@echo "  make psql               Abre psql no Postgres"
	@echo "  make topics             Lista os tópicos Kafka"
	@echo "  make seed               Cria 2 contas de teste (Alice/Bob) com saldo"
	@echo "  make e2e                Teste end-to-end: cria contas, faz uma transferência TED, valida saldo"
	@echo ""
	@echo "Rodar localmente (sem docker p/ apps):"
	@echo "  make run-contacorrente  dotnet run da ContaCorrente.Api (5000)"
	@echo "  make run-transferencia  dotnet run da Transferencia.Api (5001)"
	@echo "  make run-worker         dotnet run do Tarifas.Worker"
	@echo "  make run-approver       Auto-approver Python"
	@echo ""
	@echo "  make build              dotnet build da solution"
	@echo "  make test               dotnet test"

env:
	@test -f .env || cp .env.example .env
	@echo ".env pronto"

up: env
	$(COMPOSE) up -d --build
	@echo "Aguardando serviços ficarem saudáveis..."
	@sleep 5
	$(COMPOSE) ps

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

psql:
	$(PSQL)

topics:
	docker exec bankmore-kafka kafka-topics --bootstrap-server localhost:9092 --list

# ---------------------------------------------------------------------
# Seed: Alice (cpf=11111111111, R$ 10.000) e Bob (cpf=22222222222, R$ 500)
# Senha: "senha123"
# ---------------------------------------------------------------------
seed:
	@curl -fsS -X POST http://localhost:5000/api/contacorrente/criar \
	  -H "Content-Type: application/json" \
	  -d '{"nome":"Alice","cpf":"11111111111","senha":"senha123","saldoInicial":10000.00}' \
	  && echo " -> Alice criada"
	@curl -fsS -X POST http://localhost:5000/api/contacorrente/criar \
	  -H "Content-Type: application/json" \
	  -d '{"nome":"Bob","cpf":"22222222222","senha":"senha123","saldoInicial":500.00}' \
	  && echo " -> Bob criado"

# ---------------------------------------------------------------------
# e2e: cria contas, transfere R$ 200 TED Alice → Bob, valida saldos
# ---------------------------------------------------------------------
e2e: seed
	@bash scripts/e2e.sh

# ---------------------------------------------------------------------
# Run local
# ---------------------------------------------------------------------
run-contacorrente:
	cd src/BankMore.ContaCorrente.Api && $(DOTNET) run

run-transferencia:
	cd src/BankMore.Transferencia.Api && $(DOTNET) run

run-worker:
	cd src/BankMore.Tarifas.Worker && $(DOTNET) run

run-approver:
	cd pyflink && pip install -q -r requirements.txt && python3 auto_approver.py

build:
	$(DOTNET) build BankMoreSolution.sln

test:
	$(DOTNET) test BankMoreSolution.sln
