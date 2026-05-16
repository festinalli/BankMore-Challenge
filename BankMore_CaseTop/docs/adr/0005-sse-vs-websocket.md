# ADR 0005 — Painel ops via SSE (não WebSocket)

- **Data:** 2026-05-16
- **Status:** Aceita

## Contexto

Sprint 4.D pedia painel `/ops/fraude` em tempo real consumindo `fraude.alerta`
+ `transferencia.rejeitada` do Kafka.

## Alternativas

| Tech | Pró | Contra |
|---|---|---|
| **WebSocket** | Bidirecional, baixíssima latência | Handshake custoso, gerenciamento de reconexão complexo, biblioteca extra no front, sem retry automático |
| **SSE (Server-Sent Events)** | Unidirecional servidor→cliente (suficiente), API `EventSource` nativa no browser, **retry automático** se conexão cai, vai sobre HTTP/1.1 (atravessa proxies sem upgrade) | Só servidor→cliente; uma conexão por aba |
| **Polling REST** | Mais simples | Latência ruim (sentir como "ao vivo" exigiria poll < 1s = carga absurda) |

## Decisão

**SSE.** Tráfego é unidirecional (cliente só observa eventos, nunca envia). API
nativa no browser sem libs (`new EventSource(url)`). Retry automático.

## Implementação

[`FraudeOpsController.cs`](../../src/BankMore.ContaCorrente.Api/Controllers/FraudeOpsController.cs):
- Por conexão: **2 consumers Kafka efêmeros** com `groupId = "fraud-ops-{topic}-{uuid8}"` —
  cada cliente recebe **todos** os eventos novos (sem balanceamento entre clientes).
- `AutoOffsetReset.Latest` — só eventos a partir da abertura da conexão.
- `Channel<string>` bounded(256) com `DropOldest` — backpressure se cliente lento.
- Heartbeat `:heartbeat\n\n` a cada 15s pra manter conexão viva por proxies/load balancers.
- `CancellationTokenSource.CreateLinkedTokenSource(clientCt, RequestAborted)` fecha
  os 2 consumers quando cliente desconecta.

## Trade-offs

- ✅ Implementação simples (1 controller, ~150 linhas).
- ✅ Browser cuida de reconexão automática.
- ❌ Cada conexão SSE = 2 consumers Kafka — caro pra muitas conexões. Mitigado
  com [rate limit por IP](0010-rate-limit-sse.md) + cap global de 50.
- ❌ Sem auth na v1 (`/api/admin/fraude/stream` é aberto). Sprint 5: claim
  `role=ops` no JWT.
- ❌ Sem janela histórica — recarrega página perde histórico.
  Sprint 5: stream com buffer de 10min em memória ou Redis Streams.
