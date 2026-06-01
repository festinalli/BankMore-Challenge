# 0014 — Outbox DLQ + replay manual (Sprint 6.A)

**Status:** Aceito · **Data:** 2026-05-19

## Contexto

Sprint 5.B entregou outbox com retry e backoff exponencial, mas sem teto:
uma row do outbox podia ficar **ressuscitando para sempre** se o motivo do
erro fosse permanente (schema incompatível, broker derrubado fora de janela,
topic deletado). Métricas mostravam `bankmore_outbox_falhas_total` crescendo
linearmente sem freio.

## Decisão

Adicionar coluna `dead_letter_em TIMESTAMPTZ` na tabela `transferencia_outbox`:
- `NULL` = row ativa (relay processa normal)
- Não-NULL = DLQ; relay ignora, ops vê via endpoint

Política: `Outbox__MaxTentativas` (default 5). Após N tentativas
sem sucesso, o relay chama `MoverParaDeadLetter(id, motivo)` em vez de
`MarcarFalha`.

Endpoints administrativos (sem auth na v1 — Sprint 7 adiciona role=ops):

| Verbo + Rota                                  | Ação                                |
|-----------------------------------------------|-------------------------------------|
| `GET  /api/admin/outbox/dlq?limite=N`         | Lista rows em DLQ por data desc     |
| `POST /api/admin/outbox/dlq/{id}/reprocess`   | Reset dead_letter_em + tentativas=0 |

Reprocess **não** apaga `ultimo_erro` — fica histórico do incidente.

Métrica nova: `bankmore_outbox_dlq_total{motivo}`.

## Por que coluna na mesma tabela (e não tabela separada)

- Histórico unificado: tracing rastreável via `transferencia_id`
- Replay vira `UPDATE` simples sem mover bytes entre tabelas
- Index parcial `WHERE dead_letter_em IS NULL` mantém o hot-path eficiente
- Tabela separada exigiria FK extra e duplicação de schema

Sprint futuro pode separar se a DLQ crescer muito (>10k rows persistentes).

## Consequências

- ✅ Outbox para de re-tentar indefinidamente
- ✅ Ops tem visibilidade + capacidade de replay manual
- ✅ Métrica Prometheus pra alertar quando DLQ crescer
- ⚠ Sem retenção automática: DLQ rows permanecem indefinidamente.
  Sprint 7 pode adicionar `DELETE FROM transferencia_outbox WHERE
  dead_letter_em < NOW() - INTERVAL '30 days'`.
- ⚠ Endpoints admin sem auth ainda; aceitável só pela rede interna do compose.
