"""Advanced, optional ML workflows for Open ML Studio.

These endpoints extend the existing tabular engine without making an LLM/API
connection a requirement. All routes inherit the application's API password
middleware because they are mounted under /api.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sklearn.model_selection import cross_validate, StratifiedKFold, KFold, RandomizedSearchCV
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline as SkPipeline

router = APIRouter(prefix="/api", tags=["advanced-ml"])


class ValidationRequest(BaseModel):
    dataset_id: str
    target: str
    task: str = Field(pattern="^(classification|regression)$")
    algorithm: str = "random_forest"
    selected_features: list[str] | None = None
    folds: int = Field(default=5, ge=3, le=10)
    random_state: int = 42


class TuningRequest(BaseModel):
    dataset_id: str
    target: str
    task: str = Field(pattern="^(classification|regression)$")
    algorithm: str = "random_forest"
    selected_features: list[str] | None = None
    iterations: int = Field(default=12, ge=3, le=40)
    folds: int = Field(default=3, ge=3, le=5)
    random_state: int = 42


class UnsupervisedRequest(BaseModel):
    dataset_id: str
    selected_features: list[str]
    clusters: int = Field(default=3, ge=2, le=20)
    contamination: float = Field(default=0.05, gt=0.0, le=0.25)
    random_state: int = 42


def _core():
    # Lazy import avoids a module cycle while reusing the existing dataset,
    # estimator and preprocessing registries.
    from . import main
    return main


def _xy(q):
    core = _core()
    df = core.getdf(q.dataset_id).copy()
    if q.target not in df.columns:
        raise HTTPException(400, "Target column not found.")
    features = [c for c in (q.selected_features or [c for c in df.columns if c != q.target])
                if c in df.columns and c != q.target]
    if not features:
        raise HTTPException(400, "Select at least one input feature.")
    data = df[features + [q.target]].replace([np.inf, -np.inf], np.nan).dropna(subset=[q.target])
    X = data[features]
    y = data[q.target]
    if q.task == "classification":
        y = y.astype(str)
        if y.nunique() < 2 or y.nunique() > 50:
            raise HTTPException(400, "Classification requires 2–50 target classes.")
    else:
        y = pd.to_numeric(y, errors="coerce")
        valid = y.notna()
        X, y = X.loc[valid], y.loc[valid]
        if y.nunique() < 2:
            raise HTTPException(400, "Regression target must be numeric with at least two values.")
    if len(X) < 30:
        raise HTTPException(400, "At least 30 labelled rows are required.")
    return core, X, y, features


@router.post("/validate")
def validate(q: ValidationRequest):
    """Cross-validate one algorithm; returns fold scores, mean and standard deviation."""
    core, X, y, features = _xy(q)
    if q.task == "classification":
        min_class = int(y.value_counts().min())
        if min_class < q.folds:
            raise HTTPException(400, f"Each class needs at least {q.folds} rows for stratified {q.folds}-fold validation.")
        cv = StratifiedKFold(n_splits=q.folds, shuffle=True, random_state=q.random_state)
        scoring = ["accuracy", "balanced_accuracy", "f1_weighted"]
        primary = "f1_weighted"
    else:
        cv = KFold(n_splits=q.folds, shuffle=True, random_state=q.random_state)
        scoring = ["neg_mean_absolute_error", "neg_root_mean_squared_error", "r2"]
        primary = "neg_root_mean_squared_error"
    try:
        estimator = core.pipeline(X, core.estimator(q.algorithm, q.task, q.random_state))
        scores = cross_validate(estimator, X, y, cv=cv, scoring=scoring, n_jobs=-1,
                                return_train_score=False, error_score="raise")
        summary = {}
        for metric in scoring:
            values = scores[f"test_{metric}"]
            # Convert sklearn's negative loss convention back to positive errors.
            if metric.startswith("neg_"):
                values = -values
            summary[metric.replace("neg_", "")] = {
                "fold_scores": [float(v) for v in values],
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)),
            }
        return {"task": q.task, "algorithm": q.algorithm, "folds": q.folds,
                "rows": len(X), "features": features, "primary_metric": primary.replace("neg_", ""),
                "metrics": summary}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Cross-validation failed: {str(exc)[:300]}")


@router.post("/tune")
def tune(q: TuningRequest):
    """Bounded randomized hyperparameter search for tree ensembles and logistic/ridge."""
    core, X, y, features = _xy(q)
    if q.task == "classification":
        if int(y.value_counts().min()) < q.folds:
            raise HTTPException(400, f"Each class needs at least {q.folds} rows for {q.folds}-fold tuning.")
        cv = StratifiedKFold(n_splits=q.folds, shuffle=True, random_state=q.random_state)
        scoring = "f1_weighted"
        spaces = {
            "random_forest": {"model__n_estimators": [100, 200, 350], "model__max_depth": [None, 6, 10, 16], "model__min_samples_leaf": [1, 2, 4], "model__max_features": ["sqrt", 0.7]},
            "extra_trees": {"model__n_estimators": [100, 200, 350], "model__max_depth": [None, 6, 10, 16], "model__min_samples_leaf": [1, 2, 4], "model__max_features": ["sqrt", 0.7]},
            "logistic": {"model__C": [0.01, 0.1, 1.0, 10.0, 50.0]},
            "gradient_boosting": {"model__n_estimators": [80, 120, 200], "model__learning_rate": [0.03, 0.05, 0.1], "model__max_depth": [2, 3, 4]},
        }
    else:
        cv = KFold(n_splits=q.folds, shuffle=True, random_state=q.random_state)
        scoring = "neg_root_mean_squared_error"
        spaces = {
            "random_forest": {"model__n_estimators": [100, 200, 350], "model__max_depth": [None, 6, 10, 16], "model__min_samples_leaf": [1, 2, 4], "model__max_features": [1.0, 0.7]},
            "extra_trees": {"model__n_estimators": [100, 200, 350], "model__max_depth": [None, 6, 10, 16], "model__min_samples_leaf": [1, 2, 4], "model__max_features": [1.0, 0.7]},
            "ridge": {"model__alpha": [0.01, 0.1, 1.0, 10.0, 100.0]},
            "gradient_boosting": {"model__n_estimators": [80, 120, 200], "model__learning_rate": [0.03, 0.05, 0.1], "model__max_depth": [2, 3, 4]},
        }
    if q.algorithm not in spaces:
        raise HTTPException(400, f"Tuning is not configured for {q.algorithm}. Supported: {', '.join(spaces)}.")
    try:
        pipe = core.pipeline(X, core.estimator(q.algorithm, q.task, q.random_state))
        search = RandomizedSearchCV(pipe, spaces[q.algorithm], n_iter=q.iterations,
                                    scoring=scoring, cv=cv, random_state=q.random_state,
                                    n_jobs=-1, refit=True, error_score="raise")
        search.fit(X, y)
        return {"algorithm": q.algorithm, "task": q.task, "rows": len(X),
                "features": features, "folds": q.folds, "iterations": q.iterations,
                "best_score": float(-search.best_score_ if scoring.startswith("neg_") else search.best_score_),
                "score_name": "rmse" if scoring.startswith("neg_") else scoring,
                "best_parameters": search.best_params_,
                "note": "Search result is cross-validated. Run a separate untouched holdout evaluation before selecting a production model."}
    except Exception as exc:
        raise HTTPException(400, f"Hyperparameter search failed: {str(exc)[:300]}")


@router.post("/cluster")
def cluster(q: UnsupervisedRequest):
    """K-means clustering with preprocessing and optional silhouette score."""
    core = _core()
    df = core.getdf(q.dataset_id)
    features = [c for c in q.selected_features if c in df.columns]
    if not features:
        raise HTTPException(400, "Select at least one valid feature.")
    X = df[features].replace([np.inf, -np.inf], np.nan)
    numeric = X.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical = [c for c in features if c not in numeric]
    if categorical:
        # K-means requires numeric coordinates; one-hot encode categories explicitly.
        X = pd.get_dummies(X, columns=categorical, dummy_na=True, dtype=float)
    X = X.select_dtypes(include=["number", "bool"]).replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median()).fillna(0)
    if len(X) <= q.clusters or X.shape[1] == 0:
        raise HTTPException(400, "Need more rows than clusters and at least one usable feature.")
    scaler = StandardScaler()
    Z = scaler.fit_transform(X)
    estimator = KMeans(n_clusters=q.clusters, n_init=10, random_state=q.random_state)
    labels = estimator.fit_predict(Z)
    counts = np.bincount(labels, minlength=q.clusters)
    sample_idx = np.arange(len(Z)) if len(Z) <= 5000 else np.random.default_rng(q.random_state).choice(len(Z), 5000, replace=False)
    sample = Z[sample_idx]
    sample_labels = labels[sample_idx]
    sil = float(silhouette_score(sample, sample_labels)) if len(np.unique(sample_labels)) > 1 and len(sample_labels) > q.clusters else None
    return {"method": "kmeans", "rows": len(X), "features": features,
            "encoded_feature_count": int(X.shape[1]), "clusters": q.clusters,
            "cluster_counts": counts.tolist(), "silhouette_sample": sil,
            "labels_preview": labels[:1000].tolist(),
            "note": "Cluster labels are arbitrary group identifiers, not risk scores or causal explanations."}


@router.post("/anomalies")
def anomalies(q: UnsupervisedRequest):
    """Isolation Forest anomaly screening on a cleaned numeric feature matrix."""
    core = _core()
    df = core.getdf(q.dataset_id)
    features = [c for c in q.selected_features if c in df.columns]
    if not features:
        raise HTTPException(400, "Select at least one valid feature.")
    X = df[features].replace([np.inf, -np.inf], np.nan)
    numeric = X.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical = [c for c in features if c not in numeric]
    if categorical:
        X = pd.get_dummies(X, columns=categorical, dummy_na=True, dtype=float)
    X = X.select_dtypes(include=["number", "bool"]).fillna(0)
    if len(X) < 20 or X.shape[1] == 0:
        raise HTTPException(400, "Anomaly detection requires at least 20 rows and one usable feature.")
    model = IsolationForest(contamination=q.contamination, random_state=q.random_state, n_jobs=-1)
    labels = model.fit_predict(X)
    scores = -model.score_samples(X)
    idx = np.argsort(scores)[::-1][:min(100, len(scores))]
    return {"method": "isolation_forest", "rows": len(X), "features": features,
            "anomaly_count": int((labels == -1).sum()),
            "anomaly_rate": float((labels == -1).mean()),
            "top_anomalies": [{"row_index": int(i), "anomaly_score": float(scores[i])} for i in idx],
            "note": "Anomaly scores identify unusual records relative to this dataset; they do not prove fraud, error or misconduct."}
