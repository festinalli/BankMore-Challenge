# 0020 — Conformidade com o Manual de Segurança do Pix v6.0

**Status:** Aceito · **Data:** 2026-06-18 · **Supera em parte:** [0019](0019-sprint10-streaming-pos-liquidacao-mtls.md)

## Contexto

O BACEN publicou em 08/06/2026 a versão 6.0 do **Manual de Segurança do SFN,
Volume II — Segurança do Pix**. Três mudanças incidem diretamente sobre a camada
mTLS/RSFN que a Sprint 10.B (ADR 0019) introduziu:

| § | Exigência | Estado antes desta mudança |
|---|---|---|
| **2.1** | Controle de origem de acesso à ICOM (IP allowlist) + monitoramento | Só posse de client cert da cadeia; sem allowlist, sem auditoria de origem, ICOM na mesma rede do resto do stack, portas em 0.0.0.0 |
| **5.1** | Separação de certificado por finalidade (canal ≠ assinatura); uso exclusivo no Pix | Só a cadeia mTLS de canal; mensagens pacs **não eram assinadas** — autenticidade dependia 100% do túnel |
| **7.1** | Proibição de armazenar chave privada para fins históricos | Sem retenção em git/DB/backup (já conforme no núcleo), mas destruição incidental, keystore compartilhado e senha de PFX default |

## Decisão

### §5.1 — Separação CERTPIC (canal) × CERTPIA (assinatura)

`gen-certs.sh` passa a emitir **dois pares por finalidade**:

- **CERTPIC** (canal mTLS): `server.pfx`/`client.pfx`, EKU `serverAuth`/`clientAuth`.
- **CERTPIA** (assinatura de mensagem): `sign-bacen-sim.pfx`/`sign-pix-api.pfx`,
  `keyUsage = digitalSignature, nonRepudiation` **crítico** e **sem** EKU de TLS.

A mensageria ISO 20022 passa a ser assinada com XMLDSig (`SignedXml`, enveloped +
Exclusive C14N + RSA-SHA256):

- `pix-api` assina a pacs.008/pacs.004 antes de enviar ao SPI e verifica a pacs.002.
- `bacen-sim` verifica a pacs.008/004 recebidas **antes de liquidar** (RJCT se
  faltar/inválida) e assina a pacs.002 de resposta.

**Não-cruzamento (verificação):** o verificador exige (1) assinatura íntegra, (2)
cert derivando da CA e (3) cert de assinatura — **rejeita** cert de canal (EKU
serverAuth/clientAuth). Por construção o CERTPIC nunca assina e o CERTPIA nunca
autentica canal. Cada cert é carregado de fonte distinta (`MTLS_SIGN_PFX` ≠
`MTLS_CLIENT_PFX`). Flag `PIX_SIGN_ENABLED` preserva compat (mTLS-só quando off).

### §2.1 — Controle de origem de acesso à ICOM

Defesa em camadas no bacen-sim (a ICOM da RSFN simulada):

1. **IP allowlist (aplicação):** middleware valida `RemoteIpAddress` (com
   `MapToIPv4` — docker entrega IPv4-mapeado) contra CIDRs de `ICOM_IP_ALLOWLIST`,
   **antes** do gate mTLS, em `/dict` e `/spi`. Origem fora da lista → 403.
2. **Segmentação de rede:** o bacen-sim sai da rede `bankmore` e fica numa rede
   dedicada `rsfn` (subnet fixa `172.30.0.0/16`). postgres/kafka/redis/etc. **não
   alcançam** a ICOM — só `pix-api` (PSP) e `prometheus` (scrape) entram na `rsfn`.
   Portas do bacen-sim passam a bind em `127.0.0.1`.
3. **Auditoria + métrica:** cada tentativa a `/dict`//`spi` é logada (IP +
   CN/thumbprint do cert + resultado) e contada em
   `bacensim_icom_acessos_total{resultado=permitido|negado_ip|negado_cert}`.

### §7.1 — Ciclo de vida da chave privada

- **Destruição segura no rollover:** `gen-certs.sh` destrói a chave anterior
  (`shred -uzn3`, fallback `rm -P` no macOS/BSD) antes de regenerar — deliberada,
  não incidental.
- **Menor privilégio:** o compose monta o material **por arquivo** (cada serviço só
  vê seu CERTPIC + CERTPIA + a CA pública); nenhum `.key` cru, pfx alheio ou `ca.key`
  entra nos containers.
- **Sem retenção histórica:** confirmado — não há chave privada em git (`.gitignore`),
  DB nem backup.

## Validação

`make e2e-pix` — 10 fluxos verdes com tudo ativo, mais asserts dedicados:

| Verificação | Resultado |
|---|---|
| §5.1 round-trip | pacs.008→verifica→pacs.002→verifica em ambos os sentidos (10 fluxos liquidam) |
| §5.1 enforcement | pacs.008 **sem** CERTPIA enviada ao SPI → **RJCT** |
| §2.1 allowlist ativa | `bacensim_icom_acessos_total{permitido}` contando |
| §2.1 deny | allowlist restritiva → origem real recebe **403** + métrica `negado_ip` |
| §2.1 isolamento | `contacorrente-api` (bankmore) **não resolve** `bacen-sim` |
| §7.1 destruição | inode da `.key` muda no rollover (destruída + recriada) |
| Observabilidade | métricas `bacensim_spi_assinatura_total` / `bacensim_icom_acessos_total` no Prometheus/Grafana |

## Consequências

- ✅ Separação de finalidade por construção + não-repúdio por mensagem (fim-a-fim).
- ✅ Controle de origem da ICOM em camadas (allowlist + rede dedicada + loopback).
- ✅ Destruição deliberada da chave + menor privilégio no keystore.
- ✅ Reversível por flag (`PIX_SIGN_ENABLED`, `ICOM_IP_ALLOWLIST_ENABLED`).

### Concessões de simulador (pendentes para "PIX produção")

- ⚠ **ICP-Brasil real:** CERTPIC/CERTPIA seriam A1/A3 de AC credenciada, não da CA
  self-signed; uso exclusivo no Pix (sem reuso em SPB/MES) é governança de PKI.
- ⚠ **HSM/token A3:** a chave privada não tocaria disco — eliminando por construção
  o risco de retenção; a destruição seria zeroização certificada (SSD comum não
  garante destruição física por wear-leveling).
- ⚠ **OCSP/CRL:** a validação de cadeia segue `RevocationMode.NoCheck`.
- ⚠ **Allowlist real:** provisionada pelo BACEN sobre IPs do ISPB homologado, em rede
  MPLS/física da RSFN, integrada a SIEM/SOC — não a docker bridge.
- ⚠ **Senha do PFX:** default de DEV (`bankmore`) com aviso ruidoso no `gen-certs.sh`;
  produção usa secret manager.
