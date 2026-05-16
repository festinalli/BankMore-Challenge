# ADR 0004 — Fail-open no ML scoring

- **Data:** 2026-05-15
- **Status:** Aceita

## Contexto

O `fraud-detector` PyFlink chama `/predict` do `fraud-ml` (XGBoost + Flask)
síncronamente pra cada transferência. Tempo típico: 60-100ms.

Pergunta crítica: **o que fazer se o ML cair**? Há dois caminhos:

1. **Fail-closed**: rejeita toda transferência enquanto ML estiver offline.
2. **Fail-open**: aprova com base apenas nas regras DURAS (auto-transf, burst, valor inválido).

## Decisão

**Fail-open com timeout de 2s** ([fraud_detector_job.py:278](../../pyflink/fraud_detector_job.py)).

Se `/predict` retorna `URLError`, `TimeoutError`, `HTTPError` ou qualquer
exceção → log de warning + segue com `score_ml = None` → decisão baseada
apenas em regras determinísticas.

## Trade-off explicado

| Cenário | Fail-closed (rejeita) | Fail-open (segue) |
|---|---|---|
| ML indisponível | 100% das transferências bloqueadas | 100% das transferências passam por regras + são logadas |
| Falso negativo (fraude passa) | Não acontece (tudo bloqueia) | Ocasional — depende das regras DURAS pegarem |
| Falso positivo (legítima bloqueada) | **Catastrófico** — todos os usuários afetados | Zero (regras DURAS são determinísticas) |
| SLA do banco | Quebra | Mantém |

A transferência financeira tem regras compliance que precisam ser respeitadas
(auto-transferência é fraude por definição, burst > N/min é throttling).
**Essas regras pegam ≥80% das fraudes operacionais**. O ML adiciona detecção
de padrões sutis (fracionamento, horário + valor médio fora do baseline).

Bloquear 100% por causa de ML offline é pior que perder a camada de detecção
sutil temporariamente. Modelo de risco: incidente do ML é alertado em segundos
(check no `bankmore-fraud-ml` healthcheck do compose), corrige em minutos.

## Observabilidade

- Log warning `"ML indisponível (fail-open): <erro>"` em cada falha.
- Sprint 5: contador Prometheus `fraud_ml_failures_total{reason=...}` + alerta
  PagerDuty quando taxa > 1% por 5min.

## Consequências

- ✅ SLA preservado em incidente do ML.
- ✅ Compliance core (auto-transf, burst) sempre ativo.
- ⚠️ Janela sem detecção fina = janela maior de fraude sofisticada. Mitigação:
  alerta de incidente é P1; recall em ≤5min.
- ⚠️ Métrica de qualidade do modelo precisa ser monitorada (precisão/recall por
  faixa de valor) pra evitar drift silencioso.
