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
import redis
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

# Sprint 4.B — feature store Redis (best-effort; sem conexão → usa placeholders)
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

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

# Conexão Redis (singleton). Best-effort: se cair, _enriquecer_do_redis devolve {}.
try:
    _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True,
                         socket_connect_timeout=1.5, socket_timeout=1.0)
    _redis.ping()
    log.info("✓ Redis conectado: %s:%d (feature store)", REDIS_HOST, REDIS_PORT)
except Exception as e:
    log.warning("⚠ Redis indisponível (%s) — features extras vão usar placeholders", e)
    _redis = None

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
    Aceita {features: {...}} ou body achatado.
    Se `cpfOrigem` for fornecido (top-level ou em features), enriquece com Redis.
    Features locais (caller) ganham precedência sobre Redis — só preenche faltantes.
    """
    f = payload.get("features", payload)
    cpf = (payload.get("cpfOrigem") or f.get("cpfOrigem") or "").strip()

    redis_feats = _enriquecer_do_redis(cpf, float(f.get("valor", 0))) if cpf else {}

    def pick(name, default):
        # Caller > Redis > default
        if name in f and f[name] is not None:
            return f[name]
        if name in redis_feats:
            return redis_feats[name]
        return default

    valor = float(f.get("valor", 0))
    out = {
        "valor":                  valor,
        "tipo":                   str(f.get("tipo", "PIX")).upper(),
        "hora_do_dia":            int(f.get("hora_do_dia", 12)),
        "dow":                    int(f.get("dow", 1)),
        "count_tx_cpf_1h":        int(pick("count_tx_cpf_1h", 0)),
        "valor_medio_cpf_24h":    float(pick("valor_medio_cpf_24h", valor)),
        "is_autotransferencia":   int(bool(f.get("is_autotransferencia", 0))),
        "valor_p95_cpf_30d":      float(pick("valor_p95_cpf_30d", valor * 2.0)),
    }
    return out


def _enriquecer_do_redis(cpf: str, valor: float) -> dict:
    """Lê features rolling do Redis. Retorna {} se Redis indisponível."""
    if _redis is None:
        return {}
    try:
        pipe = _redis.pipeline()
        pipe.get(f"feat:{cpf}:count_1h")
        pipe.lrange(f"feat:{cpf}:valores_24h", 0, -1)
        pipe.zrange(f"feat:{cpf}:valores_30d", 0, -1)
        count_1h_raw, valores_24h, valores_30d = pipe.execute()

        out: dict = {}
        if count_1h_raw is not None:
            out["count_tx_cpf_1h"] = int(count_1h_raw)
        if valores_24h:
            vals_24 = [float(v) for v in valores_24h]
            out["valor_medio_cpf_24h"] = sum(vals_24) / len(vals_24)
        if valores_30d:
            # Cada entry no ZSET é "valor:timestamp" — pega só o valor
            vals_30 = []
            for entry in valores_30d:
                try:
                    vals_30.append(float(entry.split(":")[0]))
                except (ValueError, IndexError):
                    continue
            if vals_30:
                vals_30.sort()
                idx = int(len(vals_30) * 0.95)
                out["valor_p95_cpf_30d"] = vals_30[min(idx, len(vals_30) - 1)]
        return out
    except Exception as e:
        log.debug("Redis lookup falhou (best-effort): %s", e)
        return {}


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
