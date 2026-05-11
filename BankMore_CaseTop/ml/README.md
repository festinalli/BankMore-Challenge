# ML Service — Fraud Scoring

Implementação a partir do Sprint 3 (16/05/2026).

## Componentes

- `train.ipynb` — pipeline de treino com dataset sintético (Faker + power-law, ~2% fraude).
- `app.py` — Flask + Gunicorn servindo `POST /predict`.
- `feature_pipeline.joblib` — `Pipeline` do scikit-learn (encoders + scaler).
- `model.joblib` — IsolationForest baseline → XGBoost.

## Features (rascunho)

| Feature | Origem | Janela |
|---|---|---|
| `valor_log` | request | — |
| `tipo_onehot` | request | — |
| `hora_do_dia` | request.timestamp | — |
| `dow` | request.timestamp | — |
| `valor_p95_cpf_origem_30d` | Postgres | 30d |
| `count_tx_cpf_1h` | Redis | 1h |
| `valor_medio_cpf_24h` | Redis | 24h |
| `dist_jaccard_cpf_destino_historico` | Postgres | 90d |
| `is_autotransferencia` | request | — |

## Métricas alvo

- Recall em fraude ≥ 0.85
- Precisão ≥ 0.70 (ops aceita ~30% FP no início)
- Latência p95 da chamada `/predict` < 100ms
- Drift PSI mensal < 0.2 — alerta se ultrapassar
