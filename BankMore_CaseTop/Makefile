# BankMore Case Top — Makefile

COMPOSE := docker compose --env-file .env -f infra/compose/docker-compose.yml
DOTNET  := dotnet
PSQL    := docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db

.PHONY: help env up down ps logs reset psql topics seed \
        run-contacorrente run-transferencia run-worker run-approver \
        build test e2e pyflink-deps register-schemas

help:
	@echo "BankMore Case Top — targets:"
	@echo "  make env                Cria .env a partir de .env.example (se ainda não existir)"
	@echo "  make pyflink-deps       Baixa o tarball de 220MB do apache-flink-libraries (1x)"
	@echo "  make up                 Sobe TUDO (infra + APIs + worker + fraud-detector PyFlink)"
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

pyflink-deps:
	@bash pyflink/fetch_pyflink_libs.sh

# Sprint 5.C — registra schemas Avro no Schema Registry (idempotente, BACKWARD compat).
# Os arquivos .avsc em contracts/avro/ ficam committed no git como fonte de verdade.
register-schemas:
	@bash scripts/register-schemas.sh

up: env pyflink-deps
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
# Seed idempotente: Alice (R$ 10k) e Bob (R$ 20k). 409 = já existe (OK).
# Bob tem saldo alto pra Sprint 4.A não quebrar o cenário 3 (transfere R$ 12k).
# Cenário 6 (saldo insuficiente) usa R$ 999.999 — fica acima mesmo assim.
# ---------------------------------------------------------------------
seed:
	@curl -s -o /dev/null -w "Alice: HTTP %{http_code}\n" -X POST http://localhost:5000/api/contacorrente/criar \
	  -H "Content-Type: application/json" \
	  -d '{"nome":"Alice","cpf":"11144477735","senha":"senha123","saldoInicial":500000.00}'
	@curl -s -o /dev/null -w "Bob:   HTTP %{http_code}\n" -X POST http://localhost:5000/api/contacorrente/criar \
	  -H "Content-Type: application/json" \
	  -d '{"nome":"Bob","cpf":"52998224725","senha":"senha123","saldoInicial":20000.00}'

# ---------------------------------------------------------------------
# e2e: assume seed já rodou (banco com Alice e Bob) — não recria contas.
# Para resetar tudo: make reset && make up && make seed && make e2e
# ---------------------------------------------------------------------
e2e:
	@bash scripts/e2e.sh

# e2e do PIX real (Sprint 8): DICT, liquidação ISO 20022, QR, MED, Automático, NFC, Open Finance
e2e-pix:
	@bash scripts/e2e-pix.sh

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
