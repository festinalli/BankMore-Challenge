#!/usr/bin/env bash
# Teste end-to-end do PIX real (Sprint 8) — cobre todos os fluxos:
#   1. Registro de chave DICT (Alice e Bob)
#   2. Pagamento por chave (Alice → Bob) com liquidação ISO 20022 no SPI
#   3. QR Code estático (Bob gera, Alice paga)
#   4. QR Code dinâmico/CoBV (Bob gera com valor, Alice paga)
#   5. MED — devolução com bloqueio cautelar + pacs.004 + estorno
#   6. PIX Automático — consentimento + scheduler de recorrência
#   7. PIX por Aproximação (NFC) — token efêmero single-use
#   8. Open Finance — consentimento de iniciação por terceiro
#   9. Antifraude inline — PIX altíssimo bloqueado pelo ML antes do SPI
#  10. Análise pós-liquidação streaming — pix.liquidada → feature store no Redis
#
# Pré-requisitos: make up && make seed (Alice 11144477735 / Bob 52998224725)
# Exit 0 = todos os asserts ok.

set -euo pipefail

API_CONTA=http://localhost:5000
API_PIX=http://localhost:5006
BACEN=http://localhost:5005
PSQL="docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db -t -A"

ALICE_CPF=11144477735
BOB_CPF=52998224725
ALICE_CHAVE=alice@bankmore.com
BOB_CHAVE=bob@bankmore.com

extract() { python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1',''))"; }
fail() { echo "✗ $*"; exit 1; }
ok()   { echo "✓ $*"; }

ALICE_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" -d "{\"cpf\":\"$ALICE_CPF\",\"senha\":\"senha123\"}" | extract token)
BOB_TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
  -H "Content-Type: application/json" -d "{\"cpf\":\"$BOB_CPF\",\"senha\":\"senha123\"}" | extract token)
test -n "$ALICE_TOKEN" -a -n "$BOB_TOKEN" || fail "tokens vazios"
ok "login Alice/Bob"

# Reset do estado PIX de teste: o antifraude conta transações recentes do CPF (burst),
# então execuções anteriores acumuladas fariam o ML rejeitar pagamentos legítimos.
# Zerar torna o e2e idempotente e determinístico (ambiente de teste).
$PSQL -c "DELETE FROM pix_devolucao WHERE pagamento_id IN (SELECT id FROM pix_pagamento WHERE cpf_origem IN ('$ALICE_CPF','$BOB_CPF'));" >/dev/null
$PSQL -c "DELETE FROM pix_pagamento WHERE cpf_origem IN ('$ALICE_CPF','$BOB_CPF');" >/dev/null
$PSQL -c "DELETE FROM pix_qrcode;" >/dev/null
$PSQL -c "DELETE FROM pix_consentimento WHERE cpf_pagador IN ('$ALICE_CPF','$BOB_CPF');" >/dev/null
$PSQL -c "DELETE FROM pix_nfc_token;" >/dev/null
ok "estado PIX de teste resetado (count de burst zerado)"

aliceh() { curl -fsS -H "Authorization: Bearer $ALICE_TOKEN" -H "Content-Type: application/json" "$@"; }
bobh()   { curl -fsS -H "Authorization: Bearer $BOB_TOKEN"   -H "Content-Type: application/json" "$@"; }
saldo()  { curl -fsS $API_CONTA/api/contacorrente/saldo -H "Authorization: Bearer $1" | extract saldo; }
# Pagamento SEM -f: captura o JSON mesmo em 422 (rejeição é resposta válida, não erro de transporte)
pixpay() { curl -sS -X POST "$API_PIX$2" -H "Authorization: Bearer $1" -H "Content-Type: application/json" -d "$3"; }

# ----------------------------------------------------------------------
echo; echo "▶ 1. Registro de chaves no DICT"
# Registro é idempotente do ponto de vista do teste: 400 'já registrada' é tolerado (re-run)
pixpay "$ALICE_TOKEN" /api/pix/chaves "{\"tipo\":\"EMAIL\",\"valorChave\":\"$ALICE_CHAVE\"}" >/dev/null
pixpay "$BOB_TOKEN"   /api/pix/chaves "{\"tipo\":\"EMAIL\",\"valorChave\":\"$BOB_CHAVE\"}"  >/dev/null
# Confirma no DICT do bacen-sim
RESOLVE=$(curl -fsS $BACEN/dict/entries/$BOB_CHAVE | extract cpfTitular)
test "$RESOLVE" = "$BOB_CPF" || fail "DICT não resolveu chave do Bob (veio '$RESOLVE')"
ok "chaves registradas e resolvíveis no DICT"

# ----------------------------------------------------------------------
echo; echo "▶ 2. Pagamento PIX por chave (Alice → Bob, R\$ 100)"
SB_ANTES=$(saldo $BOB_TOKEN)
RESP=$(aliceh -X POST $API_PIX/api/pix/pagar -d "{\"chaveDestino\":\"$BOB_CHAVE\",\"valor\":100.00}")
echo "  resp: $RESP"
STATUS=$(echo "$RESP" | extract status)
E2E=$(echo "$RESP" | extract e2eId)
PGTO_ID=$(echo "$RESP" | extract id)
test "$STATUS" = "LIQUIDADO" || fail "esperado LIQUIDADO, veio $STATUS"
echo "$E2E" | grep -qE '^E12345678[0-9]{12}.{11}$' || fail "EndToEndId fora do padrão BACEN: $E2E"
sleep 1
SB_DEPOIS=$(saldo $BOB_TOKEN)
test "$(echo "$SB_DEPOIS - $SB_ANTES" | bc)" = "100.00" -o "$(echo "$SB_DEPOIS > $SB_ANTES" | bc)" = "1" \
  || fail "saldo Bob não creditou (antes=$SB_ANTES depois=$SB_DEPOIS)"
ok "pagamento liquidado e2e=$E2E, Bob creditado (R\$ $SB_ANTES → R\$ $SB_DEPOIS)"

# Valida que as mensagens ISO 20022 foram persistidas
HAS_PACS=$($PSQL -c "SELECT pacs008_xml IS NOT NULL AND pacs002_xml IS NOT NULL FROM pix_pagamento WHERE id='$PGTO_ID';")
test "$HAS_PACS" = "t" || fail "pacs.008/pacs.002 não persistidos"
ok "mensagens ISO 20022 (pacs.008 + pacs.002) auditadas no banco"

# ----------------------------------------------------------------------
echo; echo "▶ 3. QR Code estático (Bob gera, Alice paga R\$ 50)"
QR=$(bobh -X POST $API_PIX/api/pix/qrcode/estatico -d "{\"chave\":\"$BOB_CHAVE\",\"valor\":50.00,\"descricao\":\"Cafe\"}")
TXID=$(echo "$QR" | extract txid)
PAYLOAD=$(echo "$QR" | extract payloadEmv)
echo "  payload EMV: ${PAYLOAD:0:60}..."
echo "$PAYLOAD" | grep -q "br.gov.bcb.pix" || fail "payload EMV sem GUI br.gov.bcb.pix"
echo "$PAYLOAD" | grep -qE "6304[0-9A-F]{4}$" || fail "payload EMV sem CRC16 no fim"
PAY=$(aliceh -X POST $API_PIX/api/pix/qrcode/pagar -d "{\"txid\":\"$TXID\"}")
test "$(echo "$PAY" | extract status)" = "LIQUIDADO" || fail "QR estático não liquidou: $PAY"
ok "QR estático pago (CRC16 EMVCo válido, liquidação OK)"

# ----------------------------------------------------------------------
echo; echo "▶ 4. QR Code dinâmico/CoBV (Bob cobra R\$ 75 com vencimento)"
VENC=$(python3 -c "import datetime;print((datetime.datetime.utcnow()+datetime.timedelta(days=1)).isoformat()+'Z')")
QRD=$(bobh -X POST $API_PIX/api/pix/qrcode/dinamico -d "{\"chave\":\"$BOB_CHAVE\",\"valor\":75.00,\"vencimento\":\"$VENC\"}")
TXIDD=$(echo "$QRD" | extract txid)
test "$(echo "$QRD" | extract tipo)" = "COBV" || fail "esperado tipo COBV, veio $(echo "$QRD" | extract tipo)"
PAYD=$(pixpay "$ALICE_TOKEN" /api/pix/qrcode/pagar "{\"txid\":\"$TXIDD\"}")
test "$(echo "$PAYD" | extract status)" = "LIQUIDADO" || fail "QR dinâmico não liquidou: $PAYD"
# Segundo pagamento do mesmo QR dinâmico deve falhar (uso único)
PAYD2=$(pixpay "$ALICE_TOKEN" /api/pix/qrcode/pagar "{\"txid\":\"$TXIDD\"}")
echo "$PAYD2" | grep -q "PAGO" || fail "QR dinâmico permitiu pagamento duplicado: $PAYD2"
ok "QR dinâmico/CoBV pago e bloqueado contra replay (uso único)"

# ----------------------------------------------------------------------
echo; echo "▶ 5. MED — devolução com bloqueio cautelar + pacs.004"
PG=$(aliceh -X POST $API_PIX/api/pix/pagar -d "{\"chaveDestino\":\"$BOB_CHAVE\",\"valor\":300.00}")
PG_ID=$(echo "$PG" | extract id)
DEV=$(aliceh -X POST $API_PIX/api/pix/med -d "{\"pagamentoId\":\"$PG_ID\",\"motivo\":\"FRAUDE\"}")
DEV_ID=$(echo "$DEV" | extract id)
test "$(echo "$DEV" | extract status)" = "BLOQUEADO" || fail "MED não bloqueou: $DEV"
ok "MED abriu com bloqueio cautelar (status BLOQUEADO, SLA 11d golpe)"
SB_PRE_DEV=$(saldo $BOB_TOKEN)
RES=$(aliceh -X POST $API_PIX/api/pix/med/$DEV_ID/resolver -d "{\"resolucao\":\"DEVOLVIDO\"}")
test "$(echo "$RES" | extract status)" = "DEVOLVIDO" || fail "MED não devolveu: $RES"
sleep 1
SB_POS_DEV=$(saldo $BOB_TOKEN)
test "$(echo "$SB_PRE_DEV > $SB_POS_DEV" | bc)" = "1" || fail "estorno não debitou Bob (pre=$SB_PRE_DEV pos=$SB_POS_DEV)"
ok "MED devolveu via pacs.004 e estornou movimentos (Bob R\$ $SB_PRE_DEV → R\$ $SB_POS_DEV)"

# ----------------------------------------------------------------------
# Isola o grupo seguinte do burst acumulado pelos fluxos 2-5 (Alice fez vários
# pagamentos em rajada — comportamento legítimo de teste, não de produção).
$PSQL -c "DELETE FROM pix_devolucao WHERE pagamento_id IN (SELECT id FROM pix_pagamento WHERE cpf_origem='$ALICE_CPF');" >/dev/null
$PSQL -c "DELETE FROM pix_pagamento WHERE cpf_origem='$ALICE_CPF';" >/dev/null

echo; echo "▶ 6. PIX Automático — consentimento + scheduler de recorrência"
CONS=$(aliceh -X POST $API_PIX/api/pix/consentimentos \
  -d "{\"tipo\":\"AUTOMATICO\",\"chaveRecebedor\":\"$BOB_CHAVE\",\"valorFixo\":29.90,\"periodicidade\":\"MENSAL\"}")
CONS_ID=$(echo "$CONS" | extract id)
aliceh -X POST $API_PIX/api/pix/consentimentos/$CONS_ID/autorizar >/dev/null
ok "consentimento PIX Automático criado e autorizado (cobra R\$ 29,90/mês)"
echo "  aguardando scheduler disparar a 1ª cobrança..."
COBRADO=""
for i in $(seq 1 20); do
  N=$($PSQL -c "SELECT count(*) FROM pix_pagamento WHERE tipo_iniciacao='AUTOMATICO' AND status='LIQUIDADO';")
  if [ "$N" -ge 1 ]; then COBRADO=1; break; fi
  sleep 2
done
test -n "$COBRADO" || fail "scheduler não disparou a cobrança recorrente em 40s"
ok "scheduler disparou cobrança recorrente automaticamente (PIX Automático)"

# ----------------------------------------------------------------------
echo; echo "▶ 7. PIX por Aproximação (NFC) — token efêmero single-use"
TOK=$(aliceh -X POST $API_PIX/api/pix/nfc/token -d "{\"valorMaximo\":200.00,\"ttlSegundos\":60}")
TOKEN=$(echo "$TOK" | extract token)
echo "$TOKEN" | grep -q "^NFC" || fail "token NFC com formato inesperado: $TOKEN"
NFCPAY=$(pixpay "$BOB_TOKEN" /api/pix/nfc/pagar "{\"token\":\"$TOKEN\",\"chaveRecebedor\":\"$BOB_CHAVE\",\"valor\":80.00}")
test "$(echo "$NFCPAY" | extract status)" = "LIQUIDADO" || fail "NFC não liquidou: $NFCPAY"
# Replay do mesmo token deve falhar (single-use)
NFCPAY2=$(pixpay "$BOB_TOKEN" /api/pix/nfc/pagar "{\"token\":\"$TOKEN\",\"chaveRecebedor\":\"$BOB_CHAVE\",\"valor\":80.00}")
echo "$NFCPAY2" | grep -q "USADO" || fail "token NFC permitiu replay: $NFCPAY2"
ok "NFC pago e token consumido (replay bloqueado)"

# ----------------------------------------------------------------------
echo; echo "▶ 8. Open Finance — consentimento de iniciação por terceiro (TPP)"
OFC=$(aliceh -X POST $API_PIX/api/pix/consentimentos \
  -d "{\"tipo\":\"OPEN_FINANCE\",\"chaveRecebedor\":\"$BOB_CHAVE\",\"valorFixo\":45.00,\"idTerceiro\":\"tpp-fintechX\"}")
OFC_ID=$(echo "$OFC" | extract id)
aliceh -X POST $API_PIX/api/pix/consentimentos/$OFC_ID/autorizar >/dev/null
OFPAY=$(aliceh -X POST $API_PIX/api/pix/consentimentos/$OFC_ID/cobrar)
test "$(echo "$OFPAY" | extract status)" = "LIQUIDADO" || fail "Open Finance não liquidou: $OFPAY"
ok "Open Finance: pagamento iniciado por terceiro liquidado"

# ----------------------------------------------------------------------
echo; echo "▶ 9. Antifraude inline — PIX de valor altíssimo bloqueado pelo ML antes do SPI"
SB_FRAUDE_ANTES=$(saldo $BOB_TOKEN)
FRAUDE=$(pixpay "$ALICE_TOKEN" /api/pix/pagar "{\"chaveDestino\":\"$BOB_CHAVE\",\"valor\":50000.00}")
echo "  resp: $FRAUDE"
test "$(echo "$FRAUDE" | extract status)" = "REJEITADO" || fail "esperado REJEITADO por fraude, veio $(echo "$FRAUDE" | extract status)"
echo "$FRAUDE" | grep -q "ANALISE_FRAUDE" || fail "motivo não é ANALISE_FRAUDE: $FRAUDE"
SCORE=$(echo "$FRAUDE" | extract scoreFraude)
python3 -c "import sys; sys.exit(0 if float('$SCORE')>=0.95 else 1)" || fail "score $SCORE abaixo do threshold"
sleep 1
SB_FRAUDE_DEPOIS=$(saldo $BOB_TOKEN)
test "$SB_FRAUDE_ANTES" = "$SB_FRAUDE_DEPOIS" || fail "saldo Bob mudou — PIX fraudulento liquidou! (antes=$SB_FRAUDE_ANTES depois=$SB_FRAUDE_DEPOIS)"
# Confirma que NÃO foi ao SPI (pacs008 nulo p/ rejeitado por fraude — bloqueado antes da liquidação)
FRAUDE_ID=$(echo "$FRAUDE" | extract id)
NAO_FOI_SPI=$($PSQL -c "SELECT pacs008_xml IS NULL FROM pix_pagamento WHERE id='$FRAUDE_ID';")
test "$NAO_FOI_SPI" = "t" || fail "PIX fraudulento chegou a montar pacs.008 (deveria bloquear antes)"
ok "PIX fraudulento bloqueado pelo ML (score=$SCORE) ANTES do SPI, sem liquidar"

# ----------------------------------------------------------------------
echo; echo "▶ 10. Análise pós-liquidação streaming — pix.liquidada enriquece feature store"
REDIS="docker exec bankmore-redis redis-cli"
$REDIS DEL feat:$ALICE_CPF:count_1h >/dev/null
PAY10=$(pixpay "$ALICE_TOKEN" /api/pix/pagar "{\"chaveDestino\":\"$BOB_CHAVE\",\"valor\":42.00}")
test "$(echo "$PAY10" | extract status)" = "LIQUIDADO" || fail "pagamento p/ teste streaming não liquidou: $PAY10"
# O worker consome pix.liquidada async e atualiza o Redis — espera o enriquecimento
ENRIQUECEU=""
for i in $(seq 1 15); do
  C=$($REDIS GET feat:$ALICE_CPF:count_1h 2>/dev/null | tr -d '[:space:]')
  if [ -n "$C" ] && [ "$C" -ge 1 ] 2>/dev/null; then ENRIQUECEU=1; break; fi
  sleep 1
done
test -n "$ENRIQUECEU" || fail "feature store não foi enriquecido pelo consumer pix.liquidada em 15s"
ok "pix.liquidada consumida pelo worker → feature store Redis enriquecido (count_1h=$C)"

echo
echo "════════════════════════════════════════════════════════════"
echo "  ✓ TODOS OS 10 FLUXOS PIX PASSARAM"
echo "    (antifraude inline + análise pós-liquidação em streaming)"
echo "════════════════════════════════════════════════════════════"
