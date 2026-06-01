# 0019 — Sprint 10: Análise pós-liquidação em streaming + mTLS na RSFN

**Status:** Aceito · **Data:** 2026-06-01

## Contexto

A Sprint 9 protegeu o PIX com scoring inline (bloqueante, antes da liquidação).
Faltavam dois gaps de produção apontados no ADR 0018:
1. **Análise pós-liquidação** — defesa em profundidade em janela, sem bloquear.
2. **mTLS na RSFN** — a comunicação PSP↔BACEN real é mTLS com ICP-Brasil; o
   bacen-sim aceitava HTTP simples.

## 10.A — Análise pós-liquidação em streaming

### Decisão: dois níveis de defesa

```
        ┌─ inline (Sprint 9): rápido, BLOQUEIA antes do SPI ─┐
PIX  ───┤                                                     ├──► liquidado
        └─ streaming (10.A): pós-fato, OBSERVA + enriquece ──┘
```

- `pix-api` publica `pix.liquidada` no Kafka após cada liquidação (key=cpfOrigem
  → ordena burst do mesmo pagador na partição). Best-effort com `acks=leader`:
  perder um evento de enriquecimento não é crítico (o pagamento já liquidou e foi
  auditado no Postgres).
- `Tarifas.Worker` ganha um 3º consumer (`pix.liquidada`) que:
  - enriquece o **mesmo** feature store Redis das transferências → o histórico PIX
    passa a influenciar o scoring de **todos** os canais (inline do PIX e streaming
    da transferência). É o ponto central: defesa em profundidade real.
  - detecta burst pós-fato: `count_1h >= limiar` → métrica `bankmore_pix_alerta_burst_total`
    + log de alerta. Não bloqueia (já liquidou); alimenta investigação e o scoring
    dos **próximos** pagamentos.

Por que reusar o `Tarifas.Worker` (e não estender o PyFlink): o worker já é o dono
do feature store (Redis + StackExchange.Redis + consumer KafkaFlow). O job PyFlink
é frágil (cloudpickle, pemja) e mexer nele teria risco alto pra benefício nulo.

## 10.B — mTLS na RSFN

### Decisão: CA self-signed fazendo papel da ICP-Brasil

`infra/certs/gen-certs.sh` cria uma CA (papel da AC Raiz da ICP-Brasil) que emite:
- **server cert** pro bacen-sim (CN=bacen-sim, SAN DNS:bacen-sim)
- **client cert** pro pix-api (CN=pix-api)

Não é ICP-Brasil real (que exige A1/A3 de AC credenciada), mas é a **mesma mecânica
de mTLS**: o servidor só aceita clientes cujo cert deriva da CA confiável.

### bacen-sim (servidor)

Com `MTLS_ENABLED=true`, o Kestrel abre dois listeners:
- **8080 HTTP** — management: health, /metrics, swagger (sem mTLS)
- **8443 HTTPS** — DICT + SPI, `ClientCertificateMode.RequireCertificate` +
  validação custom da cadeia contra a CA (`CustomRootTrust`)

Um middleware bloqueia (403) tentativas de acessar `/dict` ou `/spi` via 8080 sem
client cert — garante que a interconexão interbancária só acontece sob mTLS.

### pix-api (cliente)

Os HttpClients de DICT e SPI usam `ConfigurePrimaryHttpMessageHandler` com:
- `ClientCertificates.Add(client.pfx)` — apresenta o cert no handshake
- `ServerCertificateCustomValidationCallback` — valida o cert do bacen-sim contra a
  MESMA CA (self-signed → custom root trust, não confia no trust store do SO)

### Operação

```bash
make certs   # gera a cadeia uma vez (keys NÃO vão pro git — .gitignore)
make up      # certs montados via volume read-only nos dois containers
```

`MTLS_ENABLED=false` reverte pra HTTP simples (a 8080 volta a servir DICT/SPI).

## Validação

`make e2e-pix` — 10 fluxos verdes. Específicos da Sprint 10:
- Fluxo 1 resolve o DICT **via mTLS** (HTTPS 8443 + client cert)
- Fluxo 10: `pix.liquidada` → consumer → feature store Redis enriquecido

Cenários de mTLS verificados manualmente:
| Cenário | Resultado |
|---------|-----------|
| DICT via HTTP 8080 sem cert | 403 (mTLS obrigatório) |
| DICT via HTTPS 8443 sem client cert | handshake rejeitado |
| DICT via HTTPS 8443 com client cert | 200/404 (handshake OK) |
| /health via HTTP 8080 | 200 (management) |

## Consequências

- ✅ Defesa em profundidade: inline bloqueia na borda, streaming enriquece na janela
- ✅ Histórico PIX no feature store beneficia o scoring de todos os canais
- ✅ Interconexão PSP↔BACEN sob mTLS, espelhando a RSFN
- ✅ Reversível por env (`MTLS_ENABLED`)
- ⚠ **Worker pode crashar (SIGSEGV/139)** no shutdown do librdkafka após disconnect
  do broker. Mitigado com `restart: on-failure`. Não afeta correção (Kafka persiste
  os offsets; o consumer retoma de onde parou).
- ⚠ **Certs self-signed**: a validação é contra a CA local, não a ICP-Brasil real.
  Produção exigiria certificado A1/A3 emitido por AC credenciada + OCSP/CRL.
- ⚠ **DICT in-memory**: o bacen-sim perde o diretório no restart. O registro de chave
  agora é idempotente (re-propaga pro DICT), o que restaura o estado no próximo
  registro — mas um DICT persistente seria o correto pra produção.
