# ADR 0010 — Rate limit no `/api/admin/fraude/stream`

- **Data:** 2026-05-16
- **Status:** Aceita

## Contexto

O SSE controller [`FraudeOpsController`](../../src/BankMore.ContaCorrente.Api/Controllers/FraudeOpsController.cs)
cria **2 consumers Kafka efêmeros** por conexão. Sem cap, um atacante (ou bug)
pode abrir 1000 conexões → 2000 consumers Kafka → degradação do broker.

Endpoint hoje **não tem auth** (Sprint 5 adiciona role=ops). Logo, DoS-protection
precisa estar no controller.

## Decisão

Dois níveis de limite no próprio controller (Sprint 5 migra pra
`IDistributedRateLimit` no Redis):

| Limite | Valor | Status |
|---|---|---|
| **Por IP** | 5 conexões simultâneas | `429 Too Many Requests` |
| **Global** | 50 conexões simultâneas | `503 Service Unavailable + Retry-After: 10` |

### Implementação

- `static SemaphoreSlim GlobalSlots = new(50, 50)` — cap absoluto.
- `static ConcurrentDictionary<string, int> ConnectionsPerIp` — contador atômico
  com `AddOrUpdate` em ordem ENTRY → BUSY → EXIT.
- Sempre decrementa no `finally`, mesmo se cliente cancelar.

## Trade-offs

- ✅ Proteção imediata contra DoS trivial.
- ✅ Não exige Redis (Sprint 5).
- ✅ Resposta semântica: 429 (cliente reduzir) vs 503 (serviço esgotado, retry).
- ⚠️ Por-IP cap fica em memória do processo — se escalar pra N instâncias, cap
  efetivo será `5N`. Sprint 5: `IDistributedRateLimit` (Redis) pra cap global.
- ⚠️ Sem JWT, qualquer um pode consumir os 5 slots de um IP. Sprint 5 (auth
  `role=ops`) consolida o cap por usuário.
- ⚠️ IP via `RemoteIpAddress` — atrás de LB precisa `X-Forwarded-For` parse.

## Verificação

```bash
for i in 1 2 3 4 5 6 7; do
  curl -sN --max-time 30 -o /dev/null -w "conn $i: HTTP %{http_code}\n" \
    http://localhost:5000/api/admin/fraude/stream &
done
wait
# Esperado: 5× HTTP 200, 2× HTTP 429
```
