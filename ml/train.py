"""
BankMore Fraud Model — pipeline de treino reproduzível.

Estratégia (Sprint 3):
    1. Gera dataset sintético de transações com ~2% de fraude rotulada
    2. Feature engineering (valor_log, hora_do_dia, dow, tipo OHE, flags)
    3. Treina XGBoost com class_weight pra focar em recall
    4. Compara contra IsolationForest baseline (unsupervised)
    5. Serializa artefatos em /app/artifacts/

Os artefatos são consumidos por app.py (Flask) e por chamadas HTTP do PyFlink.

Por que treinar no build (não em runtime):
    - Determinístico: mesmo seed → mesmo modelo
    - Container imutável: rollback é trivial (reusa imagem)
    - Cold-start instantâneo no Flask (joblib já está na imagem)
    - Pode ser reproduzido em CI sem GPU/dataset externo

Próximo passo (Sprint 4+):
    - Dataset real (não sintético)
    - Retraining schedule (Airflow)
    - PSI/drift monitoring
    - Shadow mode (2 modelos lado a lado, só um decide)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
SEED = 42
N_AMOSTRAS = int(os.getenv("ML_N_AMOSTRAS", "100000"))
FRACAO_FRAUDE = float(os.getenv("ML_FRACAO_FRAUDE", "0.02"))
ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "/app/artifacts"))
MODEL_VERSION = os.getenv("ML_MODEL_VERSION", "xgboost-v1")

rng = np.random.default_rng(SEED)


# -----------------------------------------------------------------------------
# Dataset sintético
# -----------------------------------------------------------------------------
@dataclass
class Sample:
    valor: float
    tipo: str
    hora_do_dia: int
    dow: int                  # 0=segunda, 6=domingo
    count_tx_cpf_1h: int
    valor_medio_cpf_24h: float
    is_autotransferencia: int
    valor_p95_cpf_30d: float
    is_fraude: int


def gerar_dataset(n: int, p_fraude: float) -> pd.DataFrame:
    """
    Gera uma amostra de transações sintéticas, com padrões de fraude plausíveis.

    Distribuição da população normal:
        - valor: lognormal(mu=5, sigma=1.2) — concentra em R$50–R$2000, cauda longa
        - tipo: PIX 70%, TED 20%, TEF 10%
        - hora_do_dia: pico 9h-22h, vale 0h-6h
        - count_1h: poisson(lambda=0.5) — maioria 0 ou 1
        - valor_medio_24h: lognormal(5, 0.8)

    Padrões de fraude (qualquer um pode tornar `is_fraude=1`):
        F1: valor muito alto (> p99 da distribuição normal)
        F2: count_1h alto (>= 5)
        F3: horário suspeito (0-5h) E valor > p90
        F4: valor_medio_24h muito diferente do valor da transação atual
        F5: combinação valor alto + horário suspeito
    """
    n_fraude_alvo = int(n * p_fraude)

    # ----- normal -----
    n_normal = n - n_fraude_alvo
    valor = rng.lognormal(mean=5.0, sigma=1.2, size=n_normal)
    tipo = rng.choice(["PIX", "TED", "TEF"], size=n_normal, p=[0.70, 0.20, 0.10])
    # hora_do_dia: pico durante o dia
    hora = rng.choice(np.arange(24), size=n_normal, p=_hora_pdf())
    dow = rng.integers(0, 7, size=n_normal)
    count_1h = rng.poisson(lam=0.5, size=n_normal).clip(0, 10)
    valor_medio_24h = rng.lognormal(mean=5.0, sigma=0.8, size=n_normal)
    auto = (rng.random(n_normal) < 0.001).astype(int)  # raro mesmo na normal
    p95_30d = valor_medio_24h * rng.uniform(1.5, 3.0, size=n_normal)

    normal = pd.DataFrame({
        "valor": valor,
        "tipo": tipo,
        "hora_do_dia": hora,
        "dow": dow,
        "count_tx_cpf_1h": count_1h,
        "valor_medio_cpf_24h": valor_medio_24h,
        "is_autotransferencia": auto,
        "valor_p95_cpf_30d": p95_30d,
        "is_fraude": 0,
    })

    # ----- fraude (mistura dos 5 padrões) -----
    n_por_padrao = n_fraude_alvo // 5
    fraudes = []

    # F1: valor muito alto
    fraudes.append(_amostra_fraude(n_por_padrao, valor_min=15000, valor_max=80000))

    # F2: burst (count_1h alto)
    f2 = _amostra_fraude(n_por_padrao)
    f2["count_tx_cpf_1h"] = rng.integers(5, 12, size=n_por_padrao)
    fraudes.append(f2)

    # F3: noturno + valor alto
    f3 = _amostra_fraude(n_por_padrao, valor_min=3000, valor_max=15000)
    f3["hora_do_dia"] = rng.integers(0, 6, size=n_por_padrao)
    fraudes.append(f3)

    # F4: valor muito acima do padrão histórico do CPF (10x do médio)
    f4 = _amostra_fraude(n_por_padrao)
    f4["valor"] = f4["valor_medio_cpf_24h"] * rng.uniform(10, 30, size=n_por_padrao)
    fraudes.append(f4)

    # F5: autotransferência (sempre fraude no dataset)
    f5 = _amostra_fraude(n_fraude_alvo - 4 * n_por_padrao)  # resto vai aqui
    f5["is_autotransferencia"] = 1
    fraudes.append(f5)

    df = pd.concat([normal, *fraudes], ignore_index=True)
    return df.sample(frac=1.0, random_state=SEED).reset_index(drop=True)


def _hora_pdf() -> np.ndarray:
    """Distribuição realista da hora do dia (pico 9-22h)."""
    h = np.array([0.2, 0.15, 0.10, 0.10, 0.10, 0.10,  # 0-5h
                  0.30, 0.50, 0.80, 1.20, 1.40, 1.60,  # 6-11h
                  1.70, 1.80, 1.70, 1.50, 1.30, 1.20,  # 12-17h
                  1.10, 1.00, 0.90, 0.70, 0.50, 0.30])  # 18-23h
    return h / h.sum()


def _amostra_fraude(n: int, valor_min: float = None, valor_max: float = None) -> pd.DataFrame:
    valor = (rng.uniform(valor_min, valor_max, size=n)
             if valor_min is not None else rng.lognormal(5.5, 1.0, size=n))
    return pd.DataFrame({
        "valor": valor,
        "tipo": rng.choice(["PIX", "TED", "TEF"], size=n, p=[0.5, 0.3, 0.2]),
        "hora_do_dia": rng.choice(np.arange(24), size=n, p=_hora_pdf()),
        "dow": rng.integers(0, 7, size=n),
        "count_tx_cpf_1h": rng.poisson(lam=0.5, size=n).clip(0, 10),
        "valor_medio_cpf_24h": rng.lognormal(5.0, 0.8, size=n),
        "is_autotransferencia": (rng.random(n) < 0.005).astype(int),
        "valor_p95_cpf_30d": rng.lognormal(5.5, 0.8, size=n) * 2.0,
        "is_fraude": 1,
    })


# -----------------------------------------------------------------------------
# Pipeline de features (consumido pelo Flask em runtime também)
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


def _build_pipeline(model) -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUM_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CAT_FEATURES),
        ]
    )
    return Pipeline([("pre", pre), ("model", model)])


# -----------------------------------------------------------------------------
# Treino + comparação
# -----------------------------------------------------------------------------
def treinar(df: pd.DataFrame) -> dict:
    X = df.drop(columns=["is_fraude"])
    y = df["is_fraude"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=SEED
    )

    # Baseline: IsolationForest unsupervised — usa só X_train, sem labels
    iso_pipe = _build_pipeline(IsolationForest(
        n_estimators=200,
        contamination=FRACAO_FRAUDE,
        random_state=SEED,
        n_jobs=-1,
    ))
    iso_pipe.fit(X_train)
    iso_scores = -iso_pipe.named_steps["model"].score_samples(
        iso_pipe.named_steps["pre"].transform(X_test)
    )
    iso_auc = roc_auc_score(y_test, iso_scores)
    iso_ap  = average_precision_score(y_test, iso_scores)

    # XGBoost supervised — usa labels
    pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    xgb_pipe = _build_pipeline(XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.1,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        random_state=SEED,
        n_jobs=-1,
        tree_method="hist",
    ))
    xgb_pipe.fit(X_train, y_train)
    xgb_scores = xgb_pipe.predict_proba(X_test)[:, 1]
    xgb_pred = (xgb_scores >= 0.5).astype(int)
    xgb_auc = roc_auc_score(y_test, xgb_scores)
    xgb_ap  = average_precision_score(y_test, xgb_scores)

    # Achar threshold com >= 0.85 recall
    prec, rec, thr = precision_recall_curve(y_test, xgb_scores)
    # rec/prec têm len = len(thr)+1; alinhar
    idx = np.where(rec[:-1] >= 0.85)[0]
    threshold_recall_85 = float(thr[idx[-1]]) if len(idx) > 0 else 0.5

    print("\n" + "=" * 60)
    print("RESULTADOS")
    print("=" * 60)
    print(f"\nIsolationForest (baseline unsupervised):")
    print(f"  ROC-AUC:                  {iso_auc:.4f}")
    print(f"  Average Precision (PR):   {iso_ap:.4f}")
    print(f"\nXGBoost (supervised, scale_pos_weight={pos_weight:.1f}):")
    print(f"  ROC-AUC:                  {xgb_auc:.4f}")
    print(f"  Average Precision (PR):   {xgb_ap:.4f}")
    print(f"\nClassification report (XGBoost, threshold=0.5):")
    print(classification_report(y_test, xgb_pred, digits=3))
    print(f"Threshold pra recall >= 0.85: {threshold_recall_85:.4f}")
    print("=" * 60)

    return {
        "model_pipeline": xgb_pipe,
        "metrics": {
            "model_version": MODEL_VERSION,
            "n_amostras": len(df),
            "fracao_fraude": float(y.mean()),
            "isolation_forest_roc_auc": float(iso_auc),
            "isolation_forest_avg_precision": float(iso_ap),
            "xgboost_roc_auc": float(xgb_auc),
            "xgboost_avg_precision": float(xgb_ap),
            "threshold_recall_85": threshold_recall_85,
            "scale_pos_weight": float(pos_weight),
            "feature_columns": NUM_FEATURES + CAT_FEATURES,
        },
    }


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    print(f"▶ Gerando dataset sintético: n={N_AMOSTRAS}, p_fraude={FRACAO_FRAUDE}")
    df = gerar_dataset(N_AMOSTRAS, FRACAO_FRAUDE)
    print(f"  ✓ shape={df.shape}, fraudes={df['is_fraude'].sum()} ({100*df['is_fraude'].mean():.2f}%)")

    print("\n▶ Treinando modelos...")
    result = treinar(df)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACT_DIR / "model.joblib"
    metrics_path = ARTIFACT_DIR / "metrics.json"

    joblib.dump(result["model_pipeline"], model_path)
    metrics_path.write_text(json.dumps(result["metrics"], indent=2))

    print(f"\n✓ Modelo salvo:  {model_path}  ({model_path.stat().st_size // 1024} KB)")
    print(f"✓ Métricas:      {metrics_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
