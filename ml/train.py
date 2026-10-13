"""
BankMore Fraud Model — pipeline de treino reproduzível.

Estratégia (Sprint 3):
    1. Gera dataset sintético de transações com ~2% de fraude rotulada (dados.py)
    2. Feature engineering (valor_log, hora_do_dia, dow, tipo OHE, flags)
    3. Treina XGBoost com class_weight pra focar em recall
    4. Compara contra IsolationForest baseline (unsupervised)
    5. Serializa artefatos em /app/artifacts/

Os artefatos são consumidos por app.py (Flask) e por chamadas HTTP do PyFlink.

Por que treinar a v1 no build:
    - Determinístico: mesmo seed → mesmo modelo
    - Cold-start instantâneo no Flask (o registro já está na imagem)
    - Pode ser reproduzido em CI sem GPU/dataset externo

Depois do build, o ciclo é outro (ADR 0023): retreinar.py gera candidatos no
registro (registro.py); o candidato roda em sombra no app.py; o portão
(portao.py) decide a promoção; registro.py reverter volta para a anterior.
Ainda falta: dataset real e agendamento do retreino.
"""
from __future__ import annotations

import json
import os
import sys
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

from dados import CAT_FEATURES, NUM_FEATURES, gerar

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
SEED = 42
N_AMOSTRAS = int(os.getenv("ML_N_AMOSTRAS", "100000"))
FRACAO_FRAUDE = float(os.getenv("ML_FRACAO_FRAUDE", "0.02"))
ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "/app/artifacts"))
MODEL_VERSION = os.getenv("ML_MODEL_VERSION", "xgboost-v1")


def gerar_dataset(n: int, p_fraude: float, seed: int = SEED) -> pd.DataFrame:
    """Compatibilidade: o mesmo dataset de antes (cenário base de dados.py)."""
    return gerar(n, p_fraude, seed, "base")


# -----------------------------------------------------------------------------
# Pipeline de features (consumido pelo Flask em runtime também)
# -----------------------------------------------------------------------------
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
def treinar(df: pd.DataFrame, seed: int = SEED, versao: str = MODEL_VERSION, verboso: bool = True) -> dict:
    X = df.drop(columns=["is_fraude"])
    y = df["is_fraude"].values
    fracao = float(y.mean())

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=seed
    )

    # Baseline: IsolationForest unsupervised — usa só X_train, sem labels
    iso_pipe = _build_pipeline(IsolationForest(
        n_estimators=200,
        contamination=fracao,
        random_state=seed,
        n_jobs=-1,
    ))
    iso_pipe.fit(X_train)
    iso_scores = -iso_pipe.named_steps["model"].score_samples(
        iso_pipe.named_steps["pre"].transform(X_test)
    )
    iso_auc = roc_auc_score(y_test, iso_scores)
    iso_ap = average_precision_score(y_test, iso_scores)

    # XGBoost supervised — usa labels
    pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    xgb_pipe = _build_pipeline(XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.1,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        random_state=seed,
        n_jobs=-1,
        tree_method="hist",
    ))
    xgb_pipe.fit(X_train, y_train)
    xgb_scores = xgb_pipe.predict_proba(X_test)[:, 1]
    xgb_pred = (xgb_scores >= 0.5).astype(int)
    xgb_auc = roc_auc_score(y_test, xgb_scores)
    xgb_ap = average_precision_score(y_test, xgb_scores)

    # Achar threshold com >= 0.85 recall
    prec, rec, thr = precision_recall_curve(y_test, xgb_scores)
    # rec/prec têm len = len(thr)+1; alinhar
    idx = np.where(rec[:-1] >= 0.85)[0]
    threshold_recall_85 = float(thr[idx[-1]]) if len(idx) > 0 else 0.5

    if verboso:
        print("\n" + "=" * 60)
        print("RESULTADOS (dataset sintético)")
        print("=" * 60)
        print("\nIsolationForest (baseline unsupervised):")
        print(f"  ROC-AUC:                  {iso_auc:.4f}")
        print(f"  Average Precision (PR):   {iso_ap:.4f}")
        print(f"\nXGBoost (supervised, scale_pos_weight={pos_weight:.1f}):")
        print(f"  ROC-AUC:                  {xgb_auc:.4f}")
        print(f"  Average Precision (PR):   {xgb_ap:.4f}")
        print("\nClassification report (XGBoost, threshold=0.5):")
        print(classification_report(y_test, xgb_pred, digits=3))
        print(f"Threshold pra recall >= 0.85: {threshold_recall_85:.4f}")
        print("=" * 60)

    return {
        "model_pipeline": xgb_pipe,
        "X_train": X_train,
        "scores_holdout": xgb_scores,
        "metrics": {
            "model_version": versao,
            "n_amostras": len(df),
            "fracao_fraude": fracao,
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
    """Treino do build da imagem: primeira versão, já em produção no registro."""
    from registro import Registro
    from retreinar import executar

    registro = Registro(ARTIFACT_DIR / "registro")
    if registro.existe() and MODEL_VERSION in registro.indice()["versoes"]:
        print(f"✓ {MODEL_VERSION} já está no registro; nada a treinar")
        return 0

    resultado = executar(MODEL_VERSION, cenario="base", seed=SEED, n=N_AMOSTRAS,
                         fracao_fraude=FRACAO_FRAUDE, registro=registro, motivo="treino do build")
    if registro.producao() is None:
        registro.promover(MODEL_VERSION, None, "primeira versão (build da imagem)")

    # Artefatos antigos, para quem ainda lê model.joblib e metrics.json direto.
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(resultado["model_pipeline"], ARTIFACT_DIR / "model.joblib")
    (ARTIFACT_DIR / "metrics.json").write_text(json.dumps(resultado["metrics"], indent=2))
    print(f"\n✓ {MODEL_VERSION} em produção no registro: {registro.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
