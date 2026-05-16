#!/usr/bin/env bash
# Micro-benchmark do detector PyFlink (Sprint 4.C).
# Dispara N transferências de N CPFs distintos (1 por conta — não estoura
# burst rule). Mede:
#   • latência COALESCE(efetivada_em, decidida_em) - solicitada_em (p50/p95/max) — proxy do tempo
#     ponta-a-ponta no pipeline (Kafka source → KeyedProcessFunction → ML
#     → KafkaSink).
#   • throughput de envio (transações/s).
#
# Uso: bash scripts/bench.sh [N]    (default N=20)
#
# Antes/depois: rode com parallelism=1, anote os números, troque pra 3 (ou outro),
# rebuilde só o fraud-detector (docker compose up -d --build fraud-detector),
# rode de novo.

set -euo pipefail

N=${1:-20}
API_CONTA=http://localhost:5000
API_TRANSF=http://localhost:5001
PSQL="docker exec -i bankmore-postgres psql -U bankmore -d bankmore_db -t -A"

echo "▶ bench: criando $N contas distintas (idempotente)"
for i in $(seq 1 "$N"); do
  CPF=$(printf "9%010d" "$i")
  curl -s -o /dev/null -X POST $API_CONTA/api/contacorrente/criar \
    -H "Content-Type: application/json" \
    -d "{\"nome\":\"Bench-$i\",\"cpf\":\"$CPF\",\"senha\":\"senha123\",\"saldoInicial\":1000.00}"
done
echo "  contas prontas"

echo "▶ login + disparo paralelo de $N transferências PIX R\$ 10 → Alice"
START_MS=$(python3 -c 'import time;print(int(time.time()*1000))')

for i in $(seq 1 "$N"); do
  (
    CPF=$(printf "9%010d" "$i")
    TOKEN=$(curl -fsS -X POST $API_CONTA/api/contacorrente/login \
      -H "Content-Type: application/json" \
      -d "{\"cpf\":\"$CPF\",\"senha\":\"senha123\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
    curl -s -o /dev/null -X POST $API_TRANSF/api/transferencia/efetuar \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d '{"cpfDestino":"11111111111","valor":10,"tipo":"PIX"}'
  ) &
done
wait

END_MS=$(python3 -c 'import time;print(int(time.time()*1000))')
ENVIO_MS=$((END_MS - START_MS))
THR_ENVIO=$(python3 -c "print(round($N*1000/$ENVIO_MS, 1))")
echo "  envio: $ENVIO_MS ms — throughput envio: $THR_ENVIO req/s"

echo "▶ aguardando 12s pro detector + worker fecharem o ciclo"
sleep 12

echo "▶ estatísticas das últimas $N transferências dos CPFs de bench:"
$PSQL -c "
SELECT
  COUNT(*)                                                                                              AS total,
  COUNT(*) FILTER (WHERE status='EFETIVADA')                                                            AS efetivadas,
  COUNT(*) FILTER (WHERE status IN ('REJEITADA','COMPENSADA'))                                          AS rejeitadas,
  ROUND(AVG(EXTRACT(EPOCH FROM (COALESCE(efetivada_em, decidida_em) - solicitada_em)) * 1000)::numeric, 1)                      AS lat_avg_ms,
  ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (COALESCE(efetivada_em, decidida_em) - solicitada_em)) * 1000)::numeric, 1) AS lat_p50_ms,
  ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (COALESCE(efetivada_em, decidida_em) - solicitada_em)) * 1000)::numeric, 1) AS lat_p95_ms,
  ROUND(MAX(EXTRACT(EPOCH FROM (COALESCE(efetivada_em, decidida_em) - solicitada_em)) * 1000)::numeric, 1)                      AS lat_max_ms
FROM transferencia
WHERE cpf_origem LIKE '9%' AND solicitada_em >= NOW() - INTERVAL '60 seconds';
"

# Throughput end-to-end: spread temporal das decisões
$PSQL -c "
SELECT
  ROUND((COUNT(*) * 1000.0 / NULLIF(EXTRACT(EPOCH FROM (MAX(COALESCE(efetivada_em, decidida_em)) - MIN(solicitada_em))) * 1000, 0))::numeric, 1) AS thr_e2e_req_s
FROM transferencia
WHERE cpf_origem LIKE '9%' AND solicitada_em >= NOW() - INTERVAL '60 seconds';
"
