# BankMore Case Top — Makefile
# Sprint 1: amarrar infra + APIs locais

COMPOSE     := docker compose -f infra/compose/docker-compose.yml
DOTNET      := dotnet
PSQL        := docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db

.PHONY: help up down ps logs reset psql topics seed \
        run-contacorrente run-transferencia run-worker run-approver \
        build test demo

help:
	@echo "BankMore Case Top — targets:"
	@echo "  make up                 Sobe a infra (postgres, redis, kafka, flink)"
	@echo "  make down               Derruba a infra"
	@echo "  make reset              Derruba + apaga volumes (cuidado: zera o banco)"
	@echo "  make ps                 Status dos containers"
	@echo "  make logs               Logs em tempo real"
	@echo "  make psql               Abre psql no Postgres"
	@echo "  make topics             Lista os tópicos Kafka"
	@echo "  make seed               Cria 5 contas de teste com saldo"
	@echo ""
	@echo "  make run-contacorrente  dotnet run da ContaCorrente.Api (5000)"
	@echo "  make run-transferencia  dotnet run da Transferencia.Api (5001)"
	@echo "  make run-worker         dotnet run do Tarifas.Worker"
	@echo "  make run-approver       Auto-approver Python (Sprint 1 only)"
	@echo ""
	@echo "  make build              dotnet build da solution"
	@echo "  make test               dotnet test"
	@echo "  make demo               Roteiro de demo (a ser definido)"

# -----------------------------------------------------------------
# Infra
# -----------------------------------------------------------------
up:
	$(COMPOSE) up -d
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

# -----------------------------------------------------------------
# Seed: 5 contas com saldo de R$ 10.000 cada
# Senha de todas: "senha123" (hash SHA-256 + salt fixo "saltdev1")
# CPFs: 11111111111, 22222222222, 33333333333, 44444444444, 55555555555
# -----------------------------------------------------------------
seed:
	@echo "Criando 5 contas seed via API..."
	@for cpf in 11111111111 22222222222 33333333333 44444444444 55555555555; do \
	  curl -s -X POST http://localhost:5000/api/contacorrente/criar \
	    -H "Content-Type: application/json" \
	    -d "{\"nome\":\"Cliente $$cpf\",\"cpf\":\"$$cpf\",\"senha\":\"senha123\",\"saldoInicial\":10000.00}" \
	    | tee /tmp/bankmore-seed.json ; echo ; \
	done
	@echo "Seed concluído. Login com qualquer CPF acima + senha 'senha123'."

# -----------------------------------------------------------------
# Run local (cada um em um terminal)
# -----------------------------------------------------------------
run-contacorrente:
	cd src/BankMore.ContaCorrente.Api && $(DOTNET) run

run-transferencia:
	cd src/BankMore.Transferencia.Api && $(DOTNET) run

run-worker:
	cd src/BankMore.Tarifas.Worker && $(DOTNET) run

run-approver:
	cd pyflink && pip install -q -r requirements.txt && python auto_approver.py

# -----------------------------------------------------------------
# Build & test
# -----------------------------------------------------------------
build:
	$(DOTNET) build BankMoreSolution.sln

test:
	$(DOTNET) test BankMoreSolution.sln

demo:
	@echo "TODO Sprint 4: script automatizado de demo (50 normais + burst de fraude)"
