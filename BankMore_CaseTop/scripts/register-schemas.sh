#!/usr/bin/env bash
# Sprint 5.C — registra schemas Avro no Confluent Schema Registry.
#
# Os schemas em contracts/avro/ ficam committed no git como FONTE DE VERDADE.
# Este script os sobe para o registry rodando em http://localhost:8085 com
# compatibilidade BACKWARD (consumer mais novo lê producer antigo — padrão Confluent).
#
# Subjects (estratégia TopicNameStrategy = padrão Confluent):
#   transferencia.solicitada-value  → transferencia-solicitada.avsc
#   transferencia.aprovada-value    → transferencia-decidida.avsc  (decisão APROVADA)
#   transferencia.rejeitada-value   → transferencia-decidida.avsc  (decisão REJEITADA)
#   fraude.alerta-value             → transferencia-decidida.avsc  (cópia alertada)
#
# Por que o mesmo schema serve aos 3 tópicos de saída: a estrutura é idêntica
# (TransferenciaDecidida); o campo `decisao` é o discriminador.
#
# Sprint 6 (binário Avro real):
#   producer .NET usa Confluent.SchemaRegistry.Serdes.Avro.AvroSerializer<T>
#   consumer PyFlink usa flink-avro-confluent-registry-1.18.jar
# Hoje: producer/consumer continuam JSON; o registry serve como DOCUMENTAÇÃO
# vinculada e basecamp pra migração binária.

set -euo pipefail

REGISTRY="${SCHEMA_REGISTRY_URL:-http://localhost:8085}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/contracts/avro"

if [ ! -d "$DIR" ]; then
  echo "✗ Diretório de schemas não encontrado: $DIR" >&2
  exit 1
fi

if ! curl -fsS "${REGISTRY}/subjects" >/dev/null 2>&1; then
  echo "✗ Schema Registry inacessível em ${REGISTRY}" >&2
  echo "   Sobe a stack com: make up" >&2
  exit 1
fi

register() {
  local subject="$1"
  local file="$2"
  echo "▶ Registrando ${subject} ← ${file}"

  # Schema Registry exige o schema como STRING JSON dentro de outro JSON
  local payload
  payload=$(python3 -c "
import json, sys
with open('$file') as f:
    schema = f.read()
print(json.dumps({'schema': schema}))
")

  local resp
  resp=$(curl -sS -X POST \
    -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
    -d "$payload" \
    "${REGISTRY}/subjects/${subject}/versions")

  if echo "$resp" | grep -q '"id"'; then
    local schema_id
    schema_id=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id','?'))")
    echo "  ✓ id=${schema_id}"
  else
    echo "  ✗ falha: $resp" >&2
    return 1
  fi
}

# Configura compatibilidade global default (BACKWARD = consumer N+1 lê producer N)
curl -sS -X PUT \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d '{"compatibility":"BACKWARD"}' \
  "${REGISTRY}/config" >/dev/null
echo "✓ Compatibility global = BACKWARD"

register "transferencia.solicitada-value" "$DIR/transferencia-solicitada.avsc"
register "transferencia.aprovada-value"   "$DIR/transferencia-decidida.avsc"
register "transferencia.rejeitada-value"  "$DIR/transferencia-decidida.avsc"
register "fraude.alerta-value"            "$DIR/transferencia-decidida.avsc"

echo
echo "=== Subjects registrados ==="
curl -sS "${REGISTRY}/subjects" | python3 -c "
import sys, json
for s in json.load(sys.stdin):
    print(f'  - {s}')
"
