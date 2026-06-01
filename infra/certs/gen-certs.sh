#!/usr/bin/env bash
# Gera a cadeia de certificados pra simular a RSFN (Rede do Sistema Financeiro
# Nacional) com mTLS — Sprint 10.B.
#
# No PIX real, a comunicação PSP↔BACEN trafega na RSFN com mTLS, e os certificados
# são emitidos pela ICP-Brasil (cadeia AC Raiz → AC intermediária → certificado do
# PSP). Aqui criamos uma CA self-signed fazendo o papel da "AC Raiz", emitindo:
#   - server cert pro bacen-sim (CN=bacen-sim, SAN DNS:bacen-sim)
#   - client cert pro pix-api  (CN=pix-api, usado no handshake mTLS)
#
# NÃO é ICP-Brasil real (que exige A1/A3 emitidos por AC credenciada). É a mesma
# mecânica de mTLS: o servidor só aceita clientes cujo cert foi emitido pela CA.
#
# Saída: infra/certs/*.{crt,key,pfx}. As keys NÃO vão pro git (.gitignore).

set -euo pipefail
cd "$(dirname "$0")"

PFX_PASS="${PFX_PASS:-bankmore}"
DAYS=3650

echo "▶ Gerando CA (faz o papel da AC Raiz da ICP-Brasil)..."
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days $DAYS \
  -subj "/C=BR/O=BankMore RSFN Sim/CN=BankMore Root CA" \
  -out ca.crt 2>/dev/null

gen_cert() {
  local name=$1 cn=$2 san=$3
  echo "▶ Gerando cert '$name' (CN=$cn)..."
  openssl genrsa -out "$name.key" 2048 2>/dev/null
  openssl req -new -key "$name.key" -subj "/C=BR/O=BankMore/CN=$cn" -out "$name.csr" 2>/dev/null
  # extfile com SAN + extendedKeyUsage adequado
  cat > "$name.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = $4
subjectAltName = $san
EOF
  openssl x509 -req -in "$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$name.crt" -days $DAYS -sha256 -extfile "$name.ext" 2>/dev/null
  # PFX (PKCS12) pra carga no .NET
  openssl pkcs12 -export -out "$name.pfx" -inkey "$name.key" -in "$name.crt" \
    -certfile ca.crt -passout "pass:$PFX_PASS" 2>/dev/null
  rm -f "$name.csr" "$name.ext"
}

# Server cert: serverAuth + SAN com o hostname do serviço no compose
gen_cert server  bacen-sim "DNS:bacen-sim,DNS:localhost" serverAuth
# Client cert: clientAuth (apresentado pelo pix-api no handshake)
gen_cert client  pix-api   "DNS:pix-api"                 clientAuth

rm -f ca.srl
echo "✓ Certificados gerados em infra/certs/ (PFX pass: $PFX_PASS)"
echo "  ca.crt        — CA (montada nos dois lados pra validar a cadeia)"
echo "  server.pfx    — bacen-sim (HTTPS + exige client cert)"
echo "  client.pfx    — pix-api (apresenta no mTLS)"
