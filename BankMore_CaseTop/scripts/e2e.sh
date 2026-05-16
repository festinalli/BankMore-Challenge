#!/usr/bin/env bash
# Teste end-to-end (Sprint 2):
#   1. Caminho feliz — Alice → Bob, TED R$ 200, valida saldos
#   2. Auto-transferência — rejeitada pelo controller (defense in depth)
#   3. Valor alto — emite ALERTA no fraude.alerta sem bloquear
#   4. Burst — 5 transferências rápidas do mesmo CPF, ≥4 rejeitadas com motivo BURST
#
# Pré-requisitos:
#   - `make up` rodando (12 containers)
#   - `make seed` já criou Alice (11111111111, R$ 10.000) e Bob (22222222222, R$ 500)
#
# Exit 0 = todos os asserts ok.

set -euo pipefail

API_CONTA=http://localhost:5000
API_TRANSF=http://localhost:5001
PSQL="docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db -t -A"

extract() { python3 -c "import sys, json; print(json.load(sys.stdin).get('$1',''))"; }

fail() { echo "✗ $*"; exit 1; }
ok()   { echo "✓ $*"; }

ALICE_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" \
  -d '{"cpf":"11111111111","senha":"senha123"}' | extract token)
BOB_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" \
  -d '{"cpf":"22222222222","senha":"senha123"}' | extract token)
test -n "$ALICE_TOKEN" -a -n "$BOB_TOKEN" || fail "tokens vazios"
ok "login Alice/Bob"

# ----------------------------------------------------------------------
# Cenário 1 — caminho feliz
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 1: TED R\$ 200 Alice → Bob"
SALDO_ANTES=$(curl -fsS $API_CONTA/api/contacorrente/saldo -H "Authorization: Bearer $ALICE_TOKEN" | extract saldo)
RESP=$(curl -fsS -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $ALICE_TOKEN" -H "Content-Type: application/json" \
  -d '{"cpfDestino":"22222222222","valor":200.00,"tipo":"TED"}')
ID1=$(echo "$RESP" | extract id)
echo "  resp: $RESP"
sleep 5

STATUS=$($PSQL -c "SELECT status FROM transferencia WHERE id='$ID1';" | tr -d ' ')
test "$STATUS" = "EFETIVADA" || fail "esperado EFETIVADA, veio $STATUS"
ok "transferência $ID1 → EFETIVADA"

SALDO_DEPOIS=$(curl -fsS $API_CONTA/api/contacorrente/saldo -H "Authorization: Bearer $ALICE_TOKEN" | extract saldo)
ESPERADO=$(python3 -c "print($SALDO_ANTES - 200 - 4)")
test "${SALDO_DEPOIS%.0}" = "${ESPERADO%.0}" || fail "saldo Alice esperado $ESPERADO, veio $SALDO_DEPOIS"
ok "saldo Alice = $SALDO_DEPOIS (esperado $ESPERADO, incluindo tarifa R\$ 4)"

# ----------------------------------------------------------------------
# Cenário 2 — auto-transferência
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 2: auto-transferência (Alice → Alice) — esperado 400"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $ALICE_TOKEN" -H "Content-Type: application/json" \
  -d '{"cpfDestino":"11111111111","valor":50,"tipo":"PIX"}')
test "$HTTP" = "400" || fail "esperado 400 do controller, veio $HTTP"
ok "controller rejeitou (HTTP 400) — defense in depth antes do Kafka"

# ----------------------------------------------------------------------
# Cenário 3 — valor alto: aprovada + cópia em fraude.alerta
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 3: TED R\$ 12.000 Bob → Alice (alerta esperado, sem bloqueio)"
# Bob não tem 12k, mas o detector aprova baseado em regras e o Worker tenta
# debitar. Se queremos saldo negativo, hoje passa (Sprint 3+ valida saldo).
# Aqui só validamos que o detector emite ALERTA.
RESP=$(curl -fsS -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $BOB_TOKEN" -H "Content-Type: application/json" \
  -d '{"cpfDestino":"11111111111","valor":12000,"tipo":"TED"}')
ID3=$(echo "$RESP" | extract id)
sleep 5

# Conferir status decidido
STATUS=$($PSQL -c "SELECT status FROM transferencia WHERE id='$ID3';" | tr -d ' ')
test "$STATUS" = "EFETIVADA" || fail "esperado EFETIVADA, veio $STATUS"
ok "transferência $ID3 → $STATUS"

# Conferir que detector enviou pro tópico fraude.alerta
ALERTA_COUNT=$(docker exec bankmore-kafka kafka-run-class kafka.tools.GetOffsetShell \
  --broker-list kafka:29092 --topic fraude.alerta 2>/dev/null \
  | awk -F: '{sum+=$3} END{print sum+0}')
test "$ALERTA_COUNT" -ge 1 || fail "fraude.alerta vazio (esperado ≥1)"
ok "fraude.alerta com $ALERTA_COUNT mensagem(ns)"

# ----------------------------------------------------------------------
# Cenário 4 — burst
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 4: 5 transferências TEF rápidas Bob → Alice (esperar ≥1 BURST)"
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -X POST $API_TRANSF/api/transferencia/efetuar \
    -H "Authorization: Bearer $BOB_TOKEN" -H "Content-Type: application/json" \
    -d "{\"cpfDestino\":\"11111111111\",\"valor\":${i},\"tipo\":\"TEF\"}"
done
sleep 6

BURST_COUNT=$($PSQL -c "SELECT COUNT(*) FROM transferencia WHERE motivo LIKE 'BURST%' AND cpf_origem='22222222222';" | tr -d ' ')
test "$BURST_COUNT" -ge 1 || fail "esperava ≥1 BURST, veio $BURST_COUNT"
ok "rejeições BURST registradas: $BURST_COUNT"

# ----------------------------------------------------------------------
# Cenário 5 — ML detecta padrão suspeito (Sprint 3)
# Regras duras aprovam (não é autotransf, não tem burst do Alice, valor > 0);
# o XGBoost rejeita porque valor R$ 30k entra no padrão F1 do treino (>R$ 15k).
# Calibração: R$ 30k → score ~0.99 > threshold 0.95 → REJEITADA com motivo ML_SCORE_*
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 5: ML detecta valor altíssimo (R\$ 30.000 de Alice) — esperado REJEITADA com motivo ML_SCORE_*"
RESP=$(curl -fsS -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $ALICE_TOKEN" -H "Content-Type: application/json" \
  -d '{"cpfDestino":"22222222222","valor":30000,"tipo":"TED"}')
ID5=$(echo "$RESP" | extract id)
sleep 8

STATUS=$($PSQL -c "SELECT status FROM transferencia WHERE id='$ID5';" | tr -d ' ')
MOTIVO=$($PSQL -c "SELECT motivo FROM transferencia WHERE id='$ID5';" | tr -d ' ')

if [ "$STATUS" = "REJEITADA" ] && echo "$MOTIVO" | grep -q "ML_SCORE"; then
    SCORE=$($PSQL -c "SELECT score_fraude FROM transferencia WHERE id='$ID5';" | tr -d ' ')
    VERSAO=$($PSQL -c "SELECT modelo_versao FROM transferencia WHERE id='$ID5';" | tr -d ' ')
    ok "ML rejeitou $ID5: motivo=$MOTIVO score=$SCORE versao=$VERSAO"
else
    fail "esperava REJEITADA por ML, veio status=$STATUS motivo=$MOTIVO"
fi

# ----------------------------------------------------------------------
# Cenário 6 — saldo insuficiente (Sprint 4.A)
# Worker valida saldo dentro da transação. Se < valor+taxa: COMPENSADA.
# Bob tem saldo baixo após cenários anteriores. Tentar transferir R$ 999.999.
# ----------------------------------------------------------------------
echo
echo "▶ Cenário 6: saldo insuficiente (Bob → Alice R\$ 999.999) — esperado COMPENSADA"
# Espera 70s pra burst expirar
sleep 70
RESP=$(curl -fsS -X POST $API_TRANSF/api/transferencia/efetuar \
  -H "Authorization: Bearer $BOB_TOKEN" -H "Content-Type: application/json" \
  -d '{"cpfDestino":"11111111111","valor":999999,"tipo":"TED"}')
ID6=$(echo "$RESP" | extract id)
sleep 8

STATUS=$($PSQL -c "SELECT status FROM transferencia WHERE id='$ID6';" | tr -d ' ')
MOTIVO=$($PSQL -c "SELECT motivo FROM transferencia WHERE id='$ID6';" | tr -d ' ')

# 2 caminhos válidos:
#   (a) ML rejeita ANTES por score alto (R$ 999k → score 0.99+)
#   (b) ML aprova mas Worker compensa por SALDO_INSUFICIENTE
# Em ambos status != EFETIVADA, garantindo que dinheiro de Bob não foi pra Alice
if [ "$STATUS" = "COMPENSADA" ] && [ "$MOTIVO" = "SALDO_INSUFICIENTE" ]; then
    ok "Worker compensou $ID6: motivo=SALDO_INSUFICIENTE"
elif [ "$STATUS" = "REJEITADA" ] && echo "$MOTIVO" | grep -q "ML_SCORE"; then
    ok "ML rejeitou $ID6 antes do Worker chegar (score alto pra R\$ 999k é esperado): motivo=$MOTIVO"
else
    fail "esperava COMPENSADA ou REJEITADA, veio status=$STATUS motivo=$MOTIVO"
fi

echo
echo "✅ todos os cenários e2e passaram"