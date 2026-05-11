#!/usr/bin/env bash
# Teste end-to-end Sprint 1: cria 2 contas (Alice/Bob), faz transferência TED de R$ 200,
# aguarda o pipeline (solicitada → approver → aprovada → Worker → Postgres) e valida saldos.
#
# Pré-requisitos:
#   - Contas Alice (11111111111, R$ 10.000) e Bob (22222222222, R$ 500) já criadas via `make seed`
#   - Todos os serviços rodando: docker compose ou make run-*
#
# Exit code 0 = saldos finais corretos.

set -euo pipefail

API_CONTA=http://localhost:5000
API_TRANSF=http://localhost:5001

VALOR_TED=200
TAXA_TED=4
SALDO_ALICE_ESPERADO=$(echo "10000 - $VALOR_TED - $TAXA_TED" | bc)
SALDO_BOB_ESPERADO=$(echo "500 + $VALOR_TED" | bc)

extract_token() {
  python3 -c "import sys, json; print(json.load(sys.stdin).get('token',''))"
}

extract_saldo() {
  python3 -c "import sys, json; print(json.load(sys.stdin).get('saldo','-1'))"
}

echo "▶ Login Alice"
ALICE_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" \
  -d '{"cpf":"11111111111","senha":"senha123"}' | extract_token)
test -n "$ALICE_TOKEN" || { echo "✗ Token vazio"; exit 1; }

echo "▶ Login Bob"
BOB_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" \
  -d '{"cpf":"22222222222","senha":"senha123"}' | extract_token)
test -n "$BOB_TOKEN" || { echo "✗ Token vazio"; exit 1; }

echo "▶ Transferir R\$ $VALOR_TED TED Alice → Bob"
RESPONSE=$(curl -fsS -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"cpfDestino\":\"22222222222\",\"valor\":$VALOR_TED.00,\"tipo\":\"TED\"}")
echo "  ← $RESPONSE"

echo "▶ Aguardando pipeline (5s)..."
sleep 5

echo "▶ Saldo Alice"
SALDO_ALICE=$(curl -fsS $API_CONTA/api/contacorrente/saldo -H "Authorization: Bearer $ALICE_TOKEN" | extract_saldo)
echo "▶ Saldo Bob"
SALDO_BOB=$(curl -fsS $API_CONTA/api/contacorrente/saldo -H "Authorization: Bearer $BOB_TOKEN" | extract_saldo)

echo
echo "Resultado:"
printf "  Alice: %s   (esperado %s)\n" "$SALDO_ALICE" "$SALDO_ALICE_ESPERADO"
printf "  Bob:   %s   (esperado %s)\n" "$SALDO_BOB"   "$SALDO_BOB_ESPERADO"

if [ "$(echo "$SALDO_ALICE" | sed 's/\.0*$//')" = "$SALDO_ALICE_ESPERADO" ] && \
   [ "$(echo "$SALDO_BOB"   | sed 's/\.0*$//')" = "$SALDO_BOB_ESPERADO" ]; then
  echo "✅ e2e OK"
  exit 0
else
  echo "✗ saldos divergentes"
  exit 1
fi
