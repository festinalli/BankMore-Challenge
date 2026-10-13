"""
BankMore Fraud Scoring Service — Flask + scikit-learn/XGBoost.

POST /predict
    Body:  { features: {...} }    ou diretamente { valor, tipo, hora_do_dia, ... }
    Resp:  { score: 0.0-1.0, decisao_recomendada: 'APROVAR' | 'REJEITAR',
             modelo_versao: 'xgboost-v1', latencia_ms: 12 }

GET /health      status, versão carregada e a pedida pelo registro, sombra, threshold
GET /metrics     formato Prometheus (scrape oficial)
GET /modelos     registro: produção, sombra, anteriores e histórico recente
GET /sombra      onde o modelo em sombra discordaria da produção
GET /drift       PSI de cada feature e do score na janela recente

Ciclo de vida (ADR 0023):
    - O modelo vem do registro (registro.py). O serviço confere o registro a cada
      ML_RECARGA_S segundos e troca de versão sem redeploy: promover e reverter
      pela CLI chegam aqui sozinhos. Se a recarga falhar, segue com o que já está
      carregado e conta em ml_recarga_falhas_total.
    - Modo sombra: a versão em sombra pontua a mesma transação na mesma
      requisição, depois da decisão (síncrono: soma um predict à latência).
      Nunca decide. Falhas dela, ao carregar ou ao pontuar, não afetam a produção.
    - Drift: janela das últimas ML_DRIFT_JANELA transações; a cada
      ML_DRIFT_A_CADA predições recalcula o PSI contra a referência do treino.
      Features que vieram de placeholder (sem feature store) ficam fora do PSI.

Quem barra o Pix são os consumidores (Pix API e PyFlink), com score >= 0,95; o
decisao_recomendada usa o limiar da ficha. A sombra conta discordâncias nos dois.
O Dockerfile roda 1 processo com threads, para as métricas serem do serviço todo.
Sem registro (artefatos antigos), cai no model.joblib + metrics.json de antes.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import joblib
import pandas as pd
import redis
from flask import Flask, Response, jsonify, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

import drift
from dados import ALL_FEATURES
from registro import Registro

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "/app/artifacts"))
PORT = int(os.getenv("PORT", "5003"))
# Threshold determina decisao_recomendada — calibrado pelo treino (recall >= 0.85).
# Pode ser sobrescrito via env pra testes (vale só para a produção).
THRESHOLD = float(os.getenv("ML_THRESHOLD", "0"))  # 0 = usa o da ficha do modelo
# Limiar que os consumidores aplicam (FRAUDE_THRESHOLD do Pix, ML_REJEITAR_THRESHOLD do PyFlink).
LIMIAR_CONSUMIDOR = float(os.getenv("ML_LIMIAR_CONSUMIDOR", "0.95"))
RECARGA_S = float(os.getenv("ML_RECARGA_S", "5"))
DRIFT_JANELA = int(os.getenv("ML_DRIFT_JANELA", "5000"))
DRIFT_A_CADA = int(os.getenv("ML_DRIFT_A_CADA", "100"))
SOMBRA_LOG_MAX_BYTES = int(os.getenv("ML_SOMBRA_LOG_MAX_BYTES", str(5 * 1024 * 1024)))

# Sprint 4.B — feature store Redis (best-effort; sem conexão → usa placeholders).
# REDIS_HOST vazio desliga a consulta (testes, demo local).
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ml-service")

# -----------------------------------------------------------------------------
# Prometheus metrics (formato exposition oficial).
# Histogram em segundos (convenção Prometheus); buckets cobrem 1ms..1s.
# -----------------------------------------------------------------------------
_registry = CollectorRegistry()
_metric_predicoes = Counter(
    "ml_predicoes_total",
    "Total de predições, por decisão recomendada.",
    ["decisao"],
    registry=_registry,
)
_metric_latency = Histogram(
    "ml_predict_duration_seconds",
    "Latência da inferência /predict (somente predict_proba, sem feature lookup).",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=_registry,
)
_metric_score = Histogram(
    "ml_score_distribution",
    "Distribuição dos scores retornados (0..1) — útil pra ver drift no modelo.",
    buckets=(0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
    registry=_registry,
)
_metric_redis_misses = Counter(
    "ml_feature_redis_miss_total",
    "Tentativas de lookup ao Redis que falharam (best-effort, fail-open).",
    registry=_registry,
)
_metric_placeholder = Counter(
    "ml_feature_placeholder_total",
    "Features preenchidas por placeholder (sem caller nem feature store); ficam fora do PSI.",
    ["feature"],
    registry=_registry,
)
_metric_threshold = Gauge(
    "ml_threshold",
    "Threshold de decisão da produção (decisao_recomendada = REJEITAR se score >= threshold).",
    registry=_registry,
)
_metric_modelo = Gauge(
    "ml_modelo_info",
    "Versão carregada em cada papel (valor sempre 1).",
    ["papel", "versao"],
    registry=_registry,
)
_metric_recargas = Counter(
    "ml_recargas_total",
    "Trocas de modelo a partir do registro, sem redeploy.",
    registry=_registry,
)
_metric_recarga_falhas = Counter(
    "ml_recarga_falhas_total",
    "Recargas do registro que falharam (o serviço segue com o modelo carregado).",
    registry=_registry,
)
_metric_sombra = Counter(
    "ml_sombra_predicoes_total",
    "Predições feitas pelo modelo em sombra (não decidem).",
    registry=_registry,
)
_metric_sombra_discordancias = Counter(
    "ml_sombra_discordancias_total",
    "Vezes em que a sombra decidiria diferente da produção, no limiar de cada modelo ou no dos consumidores.",
    ["direcao", "limiar"],
    registry=_registry,
)
_metric_sombra_falhas = Counter(
    "ml_sombra_falhas_total",
    "Falhas do modelo em sombra ao carregar ou ao pontuar (não afetam a resposta).",
    ["etapa"],
    registry=_registry,
)
_metric_sombra_latency = Histogram(
    "ml_sombra_duration_seconds",
    "Latência extra da sombra por requisição.",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
    registry=_registry,
)
_metric_psi = Gauge(
    "ml_feature_psi",
    "PSI da feature na janela recente contra a referência do treino.",
    ["feature"],
    registry=_registry,
)
_metric_score_psi = Gauge(
    "ml_score_psi",
    "PSI da distribuição de scores na janela recente.",
    registry=_registry,
)
_metric_janela = Gauge(
    "ml_drift_janela_amostras",
    "Transações na janela usada para o PSI.",
    registry=_registry,
)


# -----------------------------------------------------------------------------
# Modelos: produção e sombra, vindos do registro (ou dos artefatos antigos)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Modelo:
    versao: str
    pipeline: Any
    limiar: float
    referencia: dict | None

    def pontuar(self, df: pd.DataFrame) -> float:
        return float(self.pipeline.predict_proba(df)[0, 1])

    def decidir(self, score: float, limiar: float | None = None) -> str:
        return "REJEITAR" if score >= (self.limiar if limiar is None else limiar) else "APROVAR"


class Servico:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir
        self.registro = Registro(artifact_dir / "registro")
        self.producao: Modelo | None = None
        self.sombra: Modelo | None = None
        self.registro_pede: dict = {"producao": None, "sombra": None}
        self.janela = drift.Janela(DRIFT_JANELA)
        self.ultimo_drift: dict | None = None
        self._lock = Lock()
        self._stats_lock = Lock()
        self._mtime: float | None = None
        self._proxima_checagem = 0.0
        self._predicoes = 0
        self.sombra_stats = self._stats_zerados()
        self.carregar()

    @staticmethod
    def _stats_zerados() -> dict:
        return {"predicoes": 0, "falhas": 0,
                "modelo": {"sombra_rejeitaria": 0, "sombra_aprovaria": 0},
                "consumidor": {"sombra_rejeitaria": 0, "sombra_aprovaria": 0}}

    # ----- carga -----
    def carregar(self) -> None:
        if self.registro.existe():
            self._carregar_do_registro(inicial=True)
        else:
            self._carregar_legado()

    def _modelo(self, versao: str, limiar_env: float = 0.0) -> Modelo:
        ficha = self.registro.ficha(versao)
        limiar = limiar_env if limiar_env > 0 else float(ficha["limiar"])
        return Modelo(versao, self.registro.carregar(versao), limiar, ficha.get("referencia_drift"))

    def _carregar_do_registro(self, inicial: bool = False) -> None:
        """Produção primeiro: se ela falhar, nada muda. A sombra falha sozinha."""
        mtime = self.registro.indice_path.stat().st_mtime
        indice = self.registro.indice()
        self.registro_pede = {"producao": indice["producao"], "sombra": indice["sombra"]}
        if indice["producao"] is None:
            raise RuntimeError("registro sem versão em produção")
        with self._lock:
            mudou = False
            try:
                if self.producao is None or self.producao.versao != indice["producao"]:
                    self.producao = self._modelo(indice["producao"], THRESHOLD)
                    self._zerar_drift()
                    mudou = True
                pedida = indice["sombra"]
                if pedida is None and self.sombra is not None:
                    self.sombra, mudou = None, True
                elif pedida is not None and (self.sombra is None or self.sombra.versao != pedida):
                    self.sombra, mudou = self._carregar_sombra(pedida), True
                    self.sombra_stats = self._stats_zerados()
            finally:
                if mudou:
                    if not inicial:
                        _metric_recargas.inc()
                    self._publicar_versoes()
            self._mtime = mtime
        if mudou:
            log.info("✓ Modelos: produção=%s (threshold=%.4f), sombra=%s",
                     self.producao.versao, self.producao.limiar, self.sombra.versao if self.sombra else "-")

    def _carregar_sombra(self, versao: str) -> Modelo | None:
        try:
            return self._modelo(versao)
        except Exception as erro:
            _metric_sombra_falhas.labels(etapa="carga").inc()
            log.error("Sombra %s não carregou; seguindo só com a produção: %s", versao, erro)
            return None

    def _zerar_drift(self) -> None:
        """A referência mudou junto com a produção: nada calculado contra a anterior vale mais."""
        self.janela.limpar()
        self.ultimo_drift = None
        self._predicoes = 0
        _metric_psi.clear()
        _metric_score_psi.set(float("nan"))
        _metric_janela.set(0)

    def _carregar_legado(self) -> None:
        model_path = self.artifact_dir / "model.joblib"
        metrics_path = self.artifact_dir / "metrics.json"
        if not model_path.exists():
            raise RuntimeError(f"Artefato {model_path} não encontrado. Build da imagem rodou train.py?")
        metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
        limiar = THRESHOLD if THRESHOLD > 0 else metrics.get("threshold_recall_85", 0.5)
        self.producao = Modelo(metrics.get("model_version", "unknown"), joblib.load(model_path), limiar, None)
        self._publicar_versoes()
        log.info("✓ Modelo carregado (artefatos antigos, sem registro): versão=%s", self.producao.versao)

    def _publicar_versoes(self) -> None:
        _metric_modelo.clear()
        _metric_modelo.labels(papel="producao", versao=self.producao.versao).set(1)
        if self.sombra:
            _metric_modelo.labels(papel="sombra", versao=self.sombra.versao).set(1)
        _metric_threshold.set(self.producao.limiar)

    def talvez_recarregar(self) -> None:
        """Confere o registro no máximo a cada RECARGA_S; troca de versão sem redeploy."""
        agora = time.monotonic()
        if agora < self._proxima_checagem:
            return
        self._proxima_checagem = agora + RECARGA_S
        try:
            if self.registro.existe() and self.registro.indice_path.stat().st_mtime != self._mtime:
                self._carregar_do_registro()
        except Exception as erro:  # registro inconsistente: segue com o modelo que já está carregado
            _metric_recarga_falhas.inc()
            log.error("Falha ao recarregar o registro, mantendo %s: %s", self.producao.versao, erro)

    # ----- sombra e drift -----
    def pontuar_sombra(self, producao: Modelo, df: pd.DataFrame, feats: dict, score: float) -> None:
        sombra = self.sombra
        if sombra is None:
            return
        try:
            t0 = time.perf_counter()
            score_sombra = sombra.pontuar(df)
            _metric_sombra_latency.observe(time.perf_counter() - t0)
        except Exception as erro:
            _metric_sombra_falhas.labels(etapa="pontuar").inc()
            with self._stats_lock:
                self.sombra_stats["falhas"] += 1
            log.warning("Sombra %s falhou (a resposta não muda): %s", sombra.versao, erro)
            return
        _metric_sombra.inc()
        discordou = False
        with self._stats_lock:
            self.sombra_stats["predicoes"] += 1
            for limiar_nome, lim_p, lim_s in (("modelo", producao.limiar, sombra.limiar),
                                              ("consumidor", LIMIAR_CONSUMIDOR, LIMIAR_CONSUMIDOR)):
                d_p, d_s = producao.decidir(score, lim_p), sombra.decidir(score_sombra, lim_s)
                if d_p != d_s:
                    direcao = "sombra_rejeitaria" if d_s == "REJEITAR" else "sombra_aprovaria"
                    _metric_sombra_discordancias.labels(direcao=direcao, limiar=limiar_nome).inc()
                    self.sombra_stats[limiar_nome][direcao] += 1
                    discordou = True
        if discordou:
            self._registrar_discordancia(producao, sombra, feats, score, score_sombra)

    def _registrar_discordancia(self, producao: Modelo, sombra: Modelo, feats: dict, score: float, score_sombra: float) -> None:
        """sombra/<versao>.jsonl, até ML_SOMBRA_LOG_MAX_BYTES. Sem cpfOrigem; valor arredondado e hora ao minuto."""
        caminho = self.registro.dir / "sombra" / f"{sombra.versao}.jsonl"
        linha = {
            "quando": time.strftime("%Y-%m-%dT%H:%M%z"),
            "producao": {"versao": producao.versao, "score": round(score, 4)},
            "sombra": {"versao": sombra.versao, "score": round(score_sombra, 4)},
            "features": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in feats.items()},
        }
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            if caminho.exists() and caminho.stat().st_size >= SOMBRA_LOG_MAX_BYTES:
                return
            with open(caminho, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except OSError as erro:
            log.debug("Não foi possível registrar a discordância: %s", erro)

    def observar_drift(self, producao: Modelo, feats: dict, score: float, placeholders: frozenset) -> None:
        if producao.referencia is None:
            return
        self.janela.adicionar(feats, score, placeholders)
        with self._stats_lock:
            self._predicoes += 1
            calcular = self._predicoes % DRIFT_A_CADA == 0
        _metric_janela.set(len(self.janela))
        if not calcular:
            return
        resultado = self.janela.calcular(producao.referencia)
        if resultado is None or producao is not self.producao:
            return
        self.ultimo_drift = resultado
        for nome, valor in resultado["features"].items():
            _metric_psi.labels(feature=nome).set(valor)
        if resultado["score"] is not None:
            _metric_score_psi.set(resultado["score"])


servico = Servico(ARTIFACT_DIR)

# Conexão Redis (singleton). Best-effort: se cair, _enriquecer_do_redis devolve {}.
_redis = None
if REDIS_HOST:
    try:
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True,
                             socket_connect_timeout=1.5, socket_timeout=1.0)
        _redis.ping()
        log.info("✓ Redis conectado: %s:%d (feature store)", REDIS_HOST, REDIS_PORT)
    except Exception as e:
        log.warning("⚠ Redis indisponível (%s) — features extras vão usar placeholders", e)
        _redis = None

# Counters in-memory pra /metrics/json (mantido por compatibilidade)
_stats_lock = Lock()
_stats = {"total": 0, "rejeitar": 0, "aprovar": 0, "latencia_ms_total": 0.0}


# -----------------------------------------------------------------------------
# Features esperadas — alinhadas com dados.py
# -----------------------------------------------------------------------------
def _normalizar_features(payload: dict) -> tuple[dict, frozenset]:
    """
    Aceita {features: {...}} ou body achatado.
    Se `cpfOrigem` for fornecido (top-level ou em features), enriquece com Redis.
    Features locais (caller) ganham precedência sobre Redis — só preenche faltantes.
    Devolve também as features que vieram de placeholder (nem caller nem Redis).
    """
    f = payload.get("features", payload)
    cpf = (payload.get("cpfOrigem") or f.get("cpfOrigem") or "").strip()

    redis_feats = _enriquecer_do_redis(cpf, float(f.get("valor", 0))) if cpf else {}
    placeholders = set()

    def pick(name, default):
        # Caller > Redis > default
        if name in f and f[name] is not None:
            return f[name]
        if name in redis_feats:
            return redis_feats[name]
        placeholders.add(name)
        return default

    valor = float(f.get("valor", 0))
    if not math.isfinite(valor):
        raise ValueError("valor precisa ser finito")
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
    numeros = [v for k, v in out.items() if k != "tipo"]
    if not all(math.isfinite(v) for v in numeros):
        raise ValueError("valores numéricos precisam ser finitos")
    for nome in placeholders:
        _metric_placeholder.labels(feature=nome).inc()
    return out, frozenset(placeholders)


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
        _metric_redis_misses.inc()
        return {}


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Flask(__name__)


@app.get("/health")
def health():
    servico.talvez_recarregar()
    return jsonify({
        "status": "healthy",
        "model_loaded": True,
        "model_version": servico.producao.versao,
        "shadow_version": servico.sombra.versao if servico.sombra else None,
        "threshold": servico.producao.limiar,
        "registro": servico.registro.existe(),
        "registro_pede": servico.registro_pede,
    })


@app.get("/metrics")
def metrics():
    """Formato exposition Prometheus — scrape oficial."""
    return Response(generate_latest(_registry), mimetype=CONTENT_TYPE_LATEST)


@app.get("/metrics/json")
def metrics_json():
    """Endpoint JSON antigo — mantido pra compatibilidade com tooling existente."""
    with _stats_lock:
        snap = dict(_stats)
    p_rejeitar = (snap["rejeitar"] / snap["total"]) if snap["total"] else 0.0
    latencia_avg = (snap["latencia_ms_total"] / snap["total"]) if snap["total"] else 0.0
    try:
        if servico.registro.existe():
            metricas_treino = servico.registro.ficha(servico.producao.versao).get("metricas", {})
        else:
            caminho = servico.artifact_dir / "metrics.json"
            metricas_treino = json.loads(caminho.read_text()) if caminho.exists() else {}
    except (OSError, ValueError):
        metricas_treino = {}
    return jsonify({
        "model_version": servico.producao.versao,
        "threshold": servico.producao.limiar,
        "training_metrics": metricas_treino,
        "runtime": {
            "total_predicoes": snap["total"],
            "rejeitar": snap["rejeitar"],
            "aprovar": snap["aprovar"],
            "pct_rejeitar": round(p_rejeitar * 100, 2),
            "latencia_ms_media": round(latencia_avg, 2),
        },
    })


@app.get("/modelos")
def modelos():
    servico.talvez_recarregar()
    if not servico.registro.existe():
        return jsonify({"registro": False, "producao": servico.producao.versao})
    try:
        indice = servico.registro.indice()
    except (OSError, ValueError) as erro:
        return jsonify({"registro": True, "erro": f"registro ilegível: {erro}",
                        "carregado": servico.producao.versao}), 503
    return jsonify({
        "registro": True,
        "producao": indice["producao"],
        "sombra": indice["sombra"],
        "anteriores": indice["anteriores"],
        "versoes": indice["versoes"],
        "historico": indice["historico"][-10:],
        "carregado": {"producao": servico.producao.versao, "sombra": servico.sombra.versao if servico.sombra else None},
    })


@app.get("/sombra")
def sombra():
    with servico._stats_lock:
        stats = json.loads(json.dumps(servico.sombra_stats))
    def taxa(grupo: dict):
        return round(sum(grupo.values()) / stats["predicoes"], 4) if stats["predicoes"] else None
    return jsonify({
        "producao": servico.producao.versao,
        "sombra": servico.sombra.versao if servico.sombra else None,
        **stats,
        "taxa_discordancia": {"modelo": taxa(stats["modelo"]), "consumidor": taxa(stats["consumidor"])},
        "limiar_consumidor": LIMIAR_CONSUMIDOR,
    })


@app.get("/drift")
def drift_atual():
    resultado = servico.ultimo_drift
    if servico.producao.referencia is None:
        return jsonify({"disponivel": False, "motivo": "modelo sem referência de drift (artefatos antigos)"})
    if resultado is None:
        return jsonify({"disponivel": False, "amostras": len(servico.janela),
                        "motivo": f"aguardando {drift.MINIMO_DE_AMOSTRAS} transações e o próximo cálculo"})
    return jsonify({
        "disponivel": True,
        "modelo": servico.producao.versao,
        "amostras": resultado["amostras"],
        "features": {nome: {"psi": round(v, 4), "nivel": drift.classificar(v)} for nome, v in resultado["features"].items()},
        "fora_do_calculo": resultado["puladas"],
        "score": None if resultado["score"] is None else {"psi": round(resultado["score"], 4), "nivel": drift.classificar(resultado["score"])},
    })


@app.post("/predict")
def predict():
    if not request.is_json:
        return jsonify({"erro": "Content-Type deve ser application/json"}), 400

    payload = request.get_json(silent=True) or {}
    try:
        feats, placeholders = _normalizar_features(payload)
    except (TypeError, ValueError, AttributeError, OverflowError) as e:
        return jsonify({"erro": f"features inválidas: {e}"}), 400

    servico.talvez_recarregar()
    producao = servico.producao

    t0 = time.perf_counter()
    df = pd.DataFrame([feats])[ALL_FEATURES]
    score = producao.pontuar(df)
    latencia_s = time.perf_counter() - t0
    latencia_ms = latencia_s * 1000.0
    _metric_latency.observe(latencia_s)
    _metric_score.observe(score)

    decisao = producao.decidir(score)
    _metric_predicoes.labels(decisao=decisao).inc()

    with _stats_lock:
        _stats["total"] += 1
        _stats[decisao.lower()] += 1
        _stats["latencia_ms_total"] += latencia_ms

    # Depois da decisão: nada aqui muda a resposta.
    servico.pontuar_sombra(producao, df, feats, score)
    servico.observar_drift(producao, feats, score, placeholders)

    return jsonify({
        "score": round(score, 4),
        "decisao_recomendada": decisao,
        "modelo_versao": producao.versao,
        "threshold": producao.limiar,
        "latencia_ms": round(latencia_ms, 2),
    })


# -----------------------------------------------------------------------------
# Local-only dev runner — produção usa Gunicorn (Dockerfile)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
