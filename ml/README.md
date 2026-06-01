# ML Service — Fraud Scoring

Sprint 3 done — XGBoost treinado embutido em imagem Docker, servido via Flask + Gunicorn.

## Componentes

- `train.py` — pipeline reproduzível (seed=42): gera dataset sintético, treina IsolationForest + XGBoost, salva artefatos em `/app/artifacts/`. Rodado durante o `docker build`.
- `app.py` — Flask servindo `POST /predict`, `GET /health`, `GET /metrics` (in-memory counters + métricas de treino).
- `Dockerfile` — multi-stage que treina **no build** (modelo embutido) e serve com Gunicorn (2 workers sync, timeout 30s).

## Métricas do modelo atual (treino sintético)

| Métrica | IsolationForest (baseline) | XGBoost |
|---|---|---|
| ROC-AUC | 0.947 | **0.999** |
| Average Precision (PR-AUC) | 0.298 | **0.973** |

| Configuração | Valor |
|---|---|
| n_amostras | 100.000 |
| fração fraude | 2% |
| `scale_pos_weight` | 49 |
| threshold pra recall ≥ 0.85 | 0.991 |

Threshold em produção (compose): `ML_REJEITAR_THRESHOLD=0.95` — entre o 0.7 agressivo e o 0.991 do treino. Captura fraudes claras (R$ ≥ 30k → score 0.99) sem bloquear valor alto legítimo (R$ 10k → score 0.83 → APROVADA + ALERTA).

## Features que o modelo usa

| Feature | Origem | Status atual |
|---|---|---|
| `valor` | request | OK |
| `tipo` (PIX/TED/TEF, one-hot) | request | OK |
| `hora_do_dia` | event timestamp | OK |
| `dow` | event timestamp | OK |
| `count_tx_cpf_1h` | MapState do PyFlink (60s aprox) | parcial (Sprint 4 separa o state) |
| `is_autotransferencia` | regra dura já filtrou antes | sempre 0 no /predict |
| `valor_medio_cpf_24h` | feature store | **placeholder** = valor (Sprint 4) |
| `valor_p95_cpf_30d` | feature store | **placeholder** = valor × 2 (Sprint 4) |

## Padrões de fraude no dataset sintético

| Pattern | Descrição |
|---|---|
| F1 | valor > R$ 15.000 (acima do p99 da população normal) |
| F2 | ≥ 5 transações na última hora |
| F3 | noturno (0-5h) + valor > R$ 3.000 |
| F4 | valor / valor_medio_24h > 10x |
| F5 | autotransferência (mesma origem/destino) |

Em produção (Sprint 4+) o dataset real substitui esse sintético; padrões F4 e F2 dependem do feature store completar.

## Endpoints

### `GET /health`
```json
{
  "status": "healthy",
  "model_loaded": true,
  "model_version": "xgboost-v1",
  "threshold": 0.991
}
```

### `POST /predict`
```bash
curl -X POST http://localhost:5003/predict -H 'Content-Type: application/json' -d '{
  "features": {
    "valor": 15000, "tipo": "TED",
    "hora_do_dia": 3, "dow": 2,
    "count_tx_cpf_1h": 1,
    "valor_medio_cpf_24h": 200,
    "is_autotransferencia": 0,
    "valor_p95_cpf_30d": 500
  }
}'
```
```json
{
  "score": 0.9998,
  "decisao_recomendada": "REJEITAR",
  "modelo_versao": "xgboost-v1",
  "threshold": 0.991,
  "latencia_ms": 62.55
}
```

### `GET /metrics`
Counters em runtime + métricas do treino:
```json
{
  "model_version": "xgboost-v1",
  "threshold": 0.991,
  "training_metrics": { ... },
  "runtime": {
    "total_predicoes": 142,
    "rejeitar": 17,
    "aprovar": 125,
    "pct_rejeitar": 11.97,
    "latencia_ms_media": 8.14
  }
}
```

## Decisões pendentes para Sprint 4+

- Feature store completo (Redis para 1h, Postgres warm para 30d)
- Async I/O no PyFlink chamando o ML (hoje síncrono → bloqueia slot)
- Shadow mode: 2 modelos em paralelo, só um decide (A/B online)
- Retraining schedule (Airflow ou cron container)
- PSI/drift monitoring
- Substituir dataset sintético por dump anonimizado de produção
- Prometheus metrics no app.py (`prometheus_flask_exporter`)
