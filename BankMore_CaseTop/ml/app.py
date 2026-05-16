"""
BankMore Fraud Scoring Service — Flask + scikit-learn/XGBoost.

POST /predict
    Body:  { features: {...} }    ou diretamente { valor, tipo, hora_do_dia, ... }
    Resp:  { score: 0.0-1.0, decisao_recomendada: 'APROVAR' | 'REJEITAR',
             modelo_versao: 'xgboost-v1', latencia_ms: 12 }

GET /health
    Resp:  { status, model_loaded, model_version, threshold }

GET /metrics
    Resp:  métricas de treino (do metrics.json) + contadores em runtime

A latência é medida e logada por requisição (P95 vai virar métrica Prometheus
no Sprint 4 com prometheus_flask_exporter).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

import joblib
import pandas as pd
from flask import Flask, jsonify, request

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "/app/artifacts"))
MODEL_PATH = ARTIFACT_DIR / "model.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
PORT = int(os.getenv("PORT", "5003"))
# Threshold determina REJEITAR — calibrado pelo train.py (recall >= 0.85)
# Pode ser sobrescrito via env pra testes.
THRESHOLD = float(os.getenv("ML_THRESHOLD", "0"))  # 0 = usa o do metrics.json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ml-service")

# -----------------------------------------------------------------------------
# Carregar modelo (no startup, falha cedo se faltar)
# -----------------------------------------------------------------------------
if not MODEL_PATH.exists():
    raise RuntimeError(f"Artefato {MODEL_PATH} não encontrado. Build da imagem rodou train.py?")

_pipeline = joblib.load(MODEL_PATH)
_metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
_threshold = THRESHOLD if THRESHOLD > 0 else _metrics.get("threshold_recall_85", 0.5)
_model_version = _metrics.get("model_version", "unknown")

log.info("✓ Modelo carregado: versão=%s, threshold=%.4f", _model_version, _threshold)

# Counters in-memory pra /metrics
_stats_lock = Lock()
_stats = {"total": 0, "rejeitar": 0, "aprovar": 0, "latencia_ms_total": 0.0}


# -----------------------------------------------------------------------------
# Features esperadas — alinhadas com train.py
# -----------------------------------------------------------------------------
NUM_FEATURES = [
    "valor",
    "hora_do_dia",
    "dow",
    "count_tx_cpf_1h",
    "valor_medio_cpf_24h",
    "is_autotransferencia",
    "valor_p95_cpf_30d",
]
CAT_FEATURES = ["tipo"]
ALL_FEATURES = NUM_FEATURES + CAT_FEATURES


def _normalizar_features(payload: dict) -> dict:
    """
    Aceita tanto {features: {...}} quanto {valor: ..., tipo: ...} no body.
    Garante todas as features esperadas (preenche faltantes com defaults seguros).
    """
    f = payload.get("features", payload)
    out = {
        "valor":                  float(f.get("valor", 0)),
        "tipo":                   str(f.get("tipo", "PIX")).upper(),
        "hora_do_dia":            int(f.get("hora_do_dia", 12)),
        "dow":                    int(f.get("dow", 1)),
        "count_tx_cpf_1h":        int(f.get("count_tx_cpf_1h", 0)),
        "valor_medio_cpf_24h":    float(f.get("valor_medio_cpf_24h", f.get("valor", 0))),
        "is_autotransferencia":   int(bool(f.get("is_autotransferencia", 0))),
        "valor_p95_cpf_30d":      float(f.get("valor_p95_cpf_30d", f.get("valor", 0) * 2.0)),
    }
    return out


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({
        "status": "healthy",
        "model_loaded": True,
        "model_version": _model_version,
        "threshold": _threshold,
    })


@app.get("/metrics")
def metrics():
    with _stats_lock:
        snap = dict(_stats)
    p_rejeitar = (snap["rejeitar"] / snap["total"]) if snap["total"] else 0.0
    latencia_avg = (snap["latencia_ms_total"] / snap["total"]) if snap["total"] else 0.0
    return jsonify({
        "model_version": _model_version,
        "threshold": _threshold,
        "training_metrics": _metrics,
        "runtime": {
            "total_predicoes": snap["total"],
            "rejeitar": snap["rejeitar"],
            "aprovar": snap["aprovar"],
            "pct_rejeitar": round(p_rejeitar * 100, 2),
            "latencia_ms_media": round(latencia_avg, 2),
        },
    })


@app.post("/predict")
def predict():
    if not request.is_json:
        return jsonify({"erro": "Content-Type deve ser application/json"}), 400

    payload = request.get_json(silent=True) or {}
    try:
        feats = _normalizar_features(payload)
    except (TypeError, ValueError) as e:
        return jsonify({"erro": f"features inválidas: {e}"}), 400

    t0 = time.perf_counter()
    df = pd.DataFrame([feats])[ALL_FEATURES]
    score = float(_pipeline.predict_proba(df)[0, 1])
    latencia_ms = (time.perf_counter() - t0) * 1000.0

    decisao = "REJEITAR" if score >= _threshold else "APROVAR"

    with _stats_lock:
        _stats["total"] += 1
        _stats[decisao.lower()] += 1
        _stats["latencia_ms_total"] += latencia_ms

    return jsonify({
        "score": round(score, 4),
        "decisao_recomendada": decisao,
        "modelo_versao": _model_version,
        "threshold": _threshold,
        "latencia_ms": round(latencia_ms, 2),
    })


# -----------------------------------------------------------------------------
# Local-only dev runner — produção usa Gunicorn (Dockerfile)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
