# ADR 0001 — Bounded contexts: ContaCorrente e Transferência separados

- **Data:** 2026-05-10
- **Status:** Aceita

## Contexto

Versão original tinha referências cruzadas: `ContaCorrente` chamava
`Transferencia.Domain` e vice-versa. Acoplamento bidirecional → mudança
num contexto cascateava nos dois.

## Decisão

Dois bounded contexts independentes, cada um com **4 projetos**:

```
BankMore.ContaCorrente.Api          ← exposição HTTP
BankMore.ContaCorrente.Application  ← handlers MediatR (CQRS)
BankMore.ContaCorrente.Domain       ← entities, interfaces (puro, sem deps)
BankMore.ContaCorrente.Infrastructure ← Dapper repository

BankMore.Transferencia.Api
BankMore.Transferencia.Application
BankMore.Transferencia.Domain
BankMore.Transferencia.Infrastructure
```

Comunicação **só via eventos Kafka** (`transferencia.solicitada`,
`transferencia.aprovada`, etc). Sem chamadas HTTP entre contextos.

## Consequências

- ✅ Mudança no `ContaCorrente.Domain` não força recompile da Transferência.
- ✅ Deployments independentes (cada Api/Worker container separado).
- ✅ Equipes podem trabalhar em paralelo sem merge conflict cross-context.
- ✅ Eventos Kafka viram contratos públicos — força documentar (ainda JSON; Avro é roadmap).
- ⚠️ Eventual consistency: saldo na ContaCorrente reflete movimentos do
  `Tarifas.Worker` (que consome `transferencia.aprovada`). Cliente vê
  status `SOLICITADA` antes da efetivação.
- ⚠️ Sem CDC/outbox: race condition possível na Transferência.Api (persiste
  SOLICITADA + publica Kafka em duas operações). Ver roadmap Sprint 5.
