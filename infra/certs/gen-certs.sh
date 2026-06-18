#!/usr/bin/env bash
# Gera a cadeia de certificados pra simular a RSFN (Rede do Sistema Financeiro
# Nacional) com mTLS — Sprint 10.B.
#
# No PIX real, a comunicação PSP↔BACEN trafega na RSFN com mTLS, e os certificados
# são emitidos pela ICP-Brasil (cadeia AC Raiz → AC intermediária → certificado do
# PSP). Aqui criamos uma CA self-signed fazendo o papel da "AC Raiz".
#
# SEPARAÇÃO DE CERTIFICADOS POR FINALIDADE (Manual de Segurança do Pix v6.0, §5.1):
# o Manual proíbe usar o mesmo certificado para autenticar canal E assinar mensagem.
# Emitimos DOIS pares por entidade, com finalidades exclusivas e não-intercambiáveis:
#
#   CERTPIC — autenticação de CANAL (mTLS na RSFN). EKU clientAuth/serverAuth.
#     - server.pfx  → bacen-sim (CN=bacen-sim, SAN DNS:bacen-sim, serverAuth)
#     - client.pfx  → pix-api   (CN=pix-api, clientAuth, apresentado no handshake)
#
#   CERTPIA — assinatura de MENSAGEM (XMLDSig nos pacs.008/002/004). keyUsage
#     digitalSignature + nonRepudiation, SEM EKU de TLS (não pode autenticar canal).
#     - sign-bacen-sim.pfx → bacen-sim assina a pacs.002
#     - sign-pix-api.pfx   → pix-api assina a pacs.008/pacs.004
#
# Regra de não-cruzamento: o CERTPIC nunca assina mensagem e o CERTPIA nunca
# autentica canal. Em produção seriam dois certs ICP-Brasil A1/A3 distintos, de uso
# exclusivo no ecossistema Pix (sem reuso em SPB/MES).
#
# NÃO é ICP-Brasil real (que exige A1/A3 emitidos por AC credenciada). É a mesma
# mecânica de mTLS + assinatura: o servidor só aceita clientes cujo cert foi emitido
# pela CA, e cada mensagem é assinada/verificada com o cert de finalidade correta.
#
# Saída: infra/certs/*.{crt,key,pfx}. As keys NÃO vão pro git (.gitignore).

set -euo pipefail
cd "$(dirname "$0")"

PFX_PASS="${PFX_PASS:-bankmore}"
DAYS=3650

# §7.1 (Manual Pix v6.0) — proibição de armazenar chave privada para fins históricos.
# No rollover, a chave privada anterior é DESTRUÍDA (sobrescrita segura/shred), nunca
# arquivada. Não há backup nem cópia histórica de .key/.pfx (ver .gitignore). Em
# produção a destruição certificada seria feita por HSM/KMS/token A3.
destroy_key() {
  for f in "$@"; do
    [ -f "$f" ] || continue
    if command -v shred >/dev/null 2>&1; then
      shred -u -z -n 3 "$f" 2>/dev/null || rm -f "$f"
    else
      rm -P "$f" 2>/dev/null || rm -f "$f"   # macOS/BSD: rm -P sobrescreve antes de remover
    fi
  done
}
destroy_key ca.key server.key client.key sign-pix-api.key sign-bacen-sim.key \
            server.pfx client.pfx sign-pix-api.pfx sign-bacen-sim.pfx

if [ "$PFX_PASS" = "bankmore" ]; then
  echo "⚠ PFX_PASS usando o default de DEV ('bankmore'). Em produção defina PFX_PASS via" >&2
  echo "  secret e guarde a chave privada em HSM/token A3 (Manual Pix v6.0 §7.1)." >&2
fi

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

# CERTPIA (Manual Pix v6.0 §5.1) — cert de ASSINATURA de mensagem, finalidade
# distinta do cert de canal. keyUsage=digitalSignature,nonRepudiation marcado como
# crítico e SEM extendedKeyUsage de TLS: por construção não serve pra autenticar
# canal (mTLS), só pra assinar pacs. OU=Pix Signing deixa a finalidade explícita.
gen_sign_cert() {
  local name=$1 cn=$2
  echo "▶ Gerando cert de ASSINATURA '$name' (CN=$cn, CERTPIA)..."
  openssl genrsa -out "$name.key" 2048 2>/dev/null
  openssl req -new -key "$name.key" \
    -subj "/C=BR/O=BankMore/OU=Pix Signing/CN=$cn" -out "$name.csr" 2>/dev/null
  cat > "$name.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = critical, digitalSignature, nonRepudiation
EOF
  openssl x509 -req -in "$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$name.crt" -days $DAYS -sha256 -extfile "$name.ext" 2>/dev/null
  openssl pkcs12 -export -out "$name.pfx" -inkey "$name.key" -in "$name.crt" \
    -certfile ca.crt -passout "pass:$PFX_PASS" 2>/dev/null
  rm -f "$name.csr" "$name.ext"
}

# --- CERTPIC: autenticação de canal (mTLS) ---
# Server cert: serverAuth + SAN com o hostname do serviço no compose
gen_cert server  bacen-sim "DNS:bacen-sim,DNS:localhost" serverAuth
# Client cert: clientAuth (apresentado pelo pix-api no handshake)
gen_cert client  pix-api   "DNS:pix-api"                 clientAuth

# --- CERTPIA: assinatura de mensagem (XMLDSig), uma por entidade ---
gen_sign_cert sign-pix-api   pix-api-sign
gen_sign_cert sign-bacen-sim bacen-sim-sign

rm -f ca.srl
echo "✓ Certificados gerados em infra/certs/ (PFX pass: $PFX_PASS)"
echo "  ca.crt              — CA (montada nos dois lados pra validar a cadeia)"
echo "  CERTPIC (canal/mTLS):"
echo "    server.pfx        — bacen-sim (HTTPS + exige client cert)"
echo "    client.pfx        — pix-api (apresenta no mTLS)"
echo "  CERTPIA (assinatura de mensagem):"
echo "    sign-bacen-sim.pfx — bacen-sim assina a pacs.002"
echo "    sign-pix-api.pfx   — pix-api assina a pacs.008/pacs.004"
