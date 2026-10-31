"""
AFINIA — Pipeline Analítico ML-01: Árbol de Decisión y Evaluación del Modelo.
=============================================================================
Este módulo implementa el pipeline de preprocesamiento, entrenamiento reproducible,
evaluación frente a baseline (DummyClassifier) y serialización de artefactos
para el dataset de encuesta académica de AFINIA.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

# Rutas estándar del proyecto
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
DEFAULT_DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "dataset_encuesta.csv")
MODELS_DIR = os.path.join(CURRENT_DIR, "models")
REPORTS_DIR = os.path.join(CURRENT_DIR, "reports")

# Mapeo canónico de nombres de columnas
RAW_TO_CANONICAL_COLUMNS = {
    "Edad": "edad",
    "Género": "genero",
    "Gnero": "genero",
    "Ubicación": "ubicacion",
    "Ubicacin": "ubicacion",
    "Ocupación": "ocupacion",
    "Ocupacin": "ocupacion",
    "Importancia de Altura": "importancia_altura",
    "Importancia de Complexión": "importancia_complexion",
    "Importancia de Complexin": "importancia_complexion",
    "Importancia de Estilo": "importancia_estilo",
    "Importancia de Sentido del Humor": "importancia_sentido_del_humor",
    "Importancia de Ambición": "importancia_ambicion",
    "Importancia de Ambicin": "importancia_ambicion",
    "Importancia de Empatía": "importancia_empatia",
    "Importancia de Empata": "importancia_empatia",
    "Introvertido vs Extrovertido": "introvertido_vs_extrovertido",
    "Frecuencia de Ejercicio": "frecuencia_ejercicio",
    "Importancia de Compartir Hobbies": "importancia_compartir_hobbies",
    "Preferencia de Mascotas": "preferencia_mascotas",
    "Hábito de Fumar": "habito_fumar",
    "Hbito de Fumar": "habito_fumar",
    "Expresión de Afecto": "expresion_afecto",
    "Expresin de Afecto": "expresion_afecto",
    "Comunicación en Conflictos": "comunicacion_conflictos",
    "Comunicacin en Conflictos": "comunicacion_conflictos",
    "Nivel de Independencia": "nivel_independencia",
    "Impacto de Relaciones Pasadas": "impacto_relaciones_pasadas",
    "Importancia de Familia": "importancia_familia",
    "¿Qué tipo de relación buscas principalmente?": "tipo_relacion_buscada",
    "Qu tipo de relacin buscas principalmente?": "tipo_relacion_buscada",
}

NUMERIC_FEATURES = [
    "edad",
    "importancia_altura",
    "importancia_complexion",
    "importancia_estilo",
    "importancia_sentido_del_humor",
    "importancia_ambicion",
    "importancia_empatia",
    "introvertido_vs_extrovertido",
    "importancia_compartir_hobbies",
    "expresion_afecto",
    "comunicacion_conflictos",
    "nivel_independencia",
    "impacto_relaciones_pasadas",
    "importancia_familia",
]

CATEGORICAL_FEATURES = [
    "genero",
    "ubicacion",
    "ocupacion",
    "frecuencia_ejercicio",
    "preferencia_mascotas",
    "habito_fumar",
]

TARGET_COLUMN = "tipo_relacion_buscada"


def compute_file_sha256(filepath: str) -> str:
    """Calcula el hash SHA-256 de un archivo para auditoría de trazabilidad."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_dataset(filepath: str = DEFAULT_DATASET_PATH) -> pd.DataFrame:
    """
    Carga el dataset verificando existencia y probando codificaciones compatibles.
    Renombra las columnas a nombres canónicos seguros y normalizados.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset no encontrado en ruta: {filepath}")

    encodings_to_try = ["utf-8", "latin1", "cp1252", "utf-8-sig"]
    df: Optional[pd.DataFrame] = None

    for enc in encodings_to_try:
        try:
            df = pd.read_csv(filepath, encoding=enc)
            break
        except Exception:
            continue

    if df is None:
        raise ValueError(f"No fue posible leer {filepath} con codificaciones soportadas.")

    # Renombrar columnas a nombres canónicos
    rename_dict = {col: RAW_TO_CANONICAL_COLUMNS[col] for col in df.columns if col in RAW_TO_CANONICAL_COLUMNS}
    df = df.rename(columns=rename_dict)

    # Validar presencia de columnas críticas
    missing_numeric = [col for col in NUMERIC_FEATURES if col not in df.columns]
    missing_cat = [col for col in CATEGORICAL_FEATURES if col not in df.columns]
    if missing_numeric or missing_cat or TARGET_COLUMN not in df.columns:
        raise ValueError(
            f"El dataset carece de columnas requeridas. Faltan numéricas: {missing_numeric}, "
            f"categóricas: {missing_cat}, target: {TARGET_COLUMN not in df.columns}"
        )

    return df


def generate_eda_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Genera un resumen estructurado del análisis exploratorio de datos."""
    total_records = len(df)
    total_columns = len(df.columns)
    missing_per_col = df.isnull().sum().to_dict()
    duplicates_count = int(df.duplicated().sum())

    target_dist_raw = df[TARGET_COLUMN].value_counts(dropna=False).to_dict()

    cat_distributions = {}
    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            cat_distributions[col] = df[col].value_counts(dropna=False).to_dict()

    num_stats = {}
    for col in NUMERIC_FEATURES:
        if col in df.columns:
            num_stats[col] = {
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "mean": round(float(df[col].mean()), 2),
                "std": round(float(df[col].std()), 2),
            }

    return {
        "total_records": total_records,
        "total_columns": total_columns,
        "duplicate_rows": duplicates_count,
        "missing_values": missing_per_col,
        "target_distribution_raw": target_dist_raw,
        "categorical_distributions": cat_distributions,
        "numerical_statistics": num_stats,
    }


def prepare_features_and_target(
    df: pd.DataFrame,
    target_col: str = TARGET_COLUMN,
    filter_uninformative: bool = True,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Separa las variables predictoras (X) de la variable objetivo (y).
    Aplica exclusión de respuestas sin valor supervisado ('Prefiero no responder')
    y binariza la intención relacional:
        1: 'Una relación seria y estable'
        0: 'Otra orientación' ('Algo casual', 'Amistad primero y ver qué pasa')

    Garantiza ausencia de fuga: la columna target se remueve de X y nunca entra
    al conjunto de variables independientes.
    """
    if target_col not in df.columns:
        raise KeyError(f"La columna objetivo '{target_col}' no existe en el DataFrame.")

    clean_df = df.copy()

    if filter_uninformative:
        # Excluir 'Prefiero no responder'
        mask_informative = clean_df[target_col].astype(str).str.strip() != "Prefiero no responder"
        clean_df = clean_df[mask_informative].copy()

    # Binarización fundamentada
    # Clase 1: Relación seria y estable
    # Clase 0: Otra orientación (casual o amistad inicial)
    y_raw = clean_df[target_col].astype(str).str.strip()
    y = (y_raw == "Una relación seria y estable").astype(int)

    # Variables predictoras: eliminar estrictamente la columna objetivo y derivados
    feature_cols = [c for c in clean_df.columns if c != target_col]
    X = clean_df[feature_cols].copy()

    return X, y


def build_preprocessor(
    numeric_features: List[str] = NUMERIC_FEATURES,
    categorical_features: List[str] = CATEGORICAL_FEATURES,
) -> ColumnTransformer:
    """
    Construye el ColumnTransformer de scikit-learn asegurando que:
    - Las categóricas se codifiquen con OneHotEncoder(handle_unknown='ignore', sparse_output=False).
    - Las numéricas se estandaricen con StandardScaler.
    """
    numeric_transformer = StandardScaler()
    categorical_transformer = OneHotEncoder(handle_unknown="ignore", sparse_output=False)

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric_features),
            ("cat", categorical_transformer, categorical_features),
        ],
        remainder="drop",
    )
    return preprocessor


def build_decision_tree_pipeline(
    max_depth: int = 3,
    min_samples_split: int = 2,
    min_samples_leaf: int = 4,
    class_weight: Optional[str] = "balanced",
    random_state: int = 42,
) -> Pipeline:
    """Construye el Pipeline scikit-learn con DecisionTreeClassifier."""
    preprocessor = build_preprocessor()
    classifier = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_split=min_samples_split,
        min_samples_leaf=min_samples_leaf,
        class_weight=class_weight,
        random_state=random_state,
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("classifier", classifier)])


def build_dummy_baseline_pipeline(
    strategy: str = "prior",
    random_state: int = 42,
) -> Pipeline:
    """Construye el Pipeline baseline con DummyClassifier de scikit-learn."""
    preprocessor = build_preprocessor()
    classifier = DummyClassifier(strategy=strategy, random_state=random_state)
    return Pipeline(steps=[("preprocessor", preprocessor), ("classifier", classifier)])


def evaluate_pipeline(
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    cv_folds: int = 5,
) -> Dict[str, Any]:
    """
    Evalúa el pipeline calculando:
    - Validación cruzada estratificada sobre entrenamiento.
    - Rendimiento sobre entrenamiento (detección de sobreajuste).
    - Rendimiento final sobre conjunto de prueba independiente.
    - Métricas completas: accuracy, balanced_accuracy, precision, recall, f1_macro, matriz de confusión.
    """
    # 1. Validación cruzada estratificada en Train
    skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
    scoring = ["accuracy", "balanced_accuracy", "f1_macro"]
    cv_res = cross_validate(pipeline, X_train, y_train, cv=skf, scoring=scoring)

    # 2. Ajuste definitivo únicamente en entrenamiento
    pipeline.fit(X_train, y_train)

    # Predicciones
    y_train_pred = pipeline.predict(X_train)
    y_test_pred = pipeline.predict(X_test)

    # Matriz de confusión en Test: [[TN, FP], [FN, TP]]
    cm_test = confusion_matrix(y_test, y_test_pred).tolist()

    # Cálculo de métricas
    metrics = {
        "cv_5fold_train": {
            "accuracy_mean": float(round(np.mean(cv_res["test_accuracy"]), 4)),
            "accuracy_std": float(round(np.std(cv_res["test_accuracy"]), 4)),
            "balanced_accuracy_mean": float(round(np.mean(cv_res["test_balanced_accuracy"]), 4)),
            "balanced_accuracy_std": float(round(np.std(cv_res["test_balanced_accuracy"]), 4)),
            "f1_macro_mean": float(round(np.mean(cv_res["test_f1_macro"]), 4)),
            "f1_macro_std": float(round(np.std(cv_res["test_f1_macro"]), 4)),
        },
        "train_set": {
            "n_samples": int(len(y_train)),
            "class_distribution": {int(k): int(v) for k, v in y_train.value_counts().to_dict().items()},
            "accuracy": float(round(accuracy_score(y_train, y_train_pred), 4)),
            "balanced_accuracy": float(round(balanced_accuracy_score(y_train, y_train_pred), 4)),
            "f1_macro": float(round(f1_score(y_train, y_train_pred, average="macro", zero_division=0), 4)),
        },
        "test_set": {
            "n_samples": int(len(y_test)),
            "class_distribution_real": {int(k): int(v) for k, v in y_test.value_counts().to_dict().items()},
            "class_distribution_pred": {
                int(k): int(v) for k, v in pd.Series(y_test_pred).value_counts().to_dict().items()
            },
            "accuracy": float(round(accuracy_score(y_test, y_test_pred), 4)),
            "balanced_accuracy": float(round(balanced_accuracy_score(y_test, y_test_pred), 4)),
            "precision_class_0": float(
                round(precision_score(y_test, y_test_pred, pos_label=0, zero_division=0), 4)
            ),
            "recall_class_0": float(round(recall_score(y_test, y_test_pred, pos_label=0, zero_division=0), 4)),
            "precision_class_1": float(
                round(precision_score(y_test, y_test_pred, pos_label=1, zero_division=0), 4)
            ),
            "recall_class_1": float(round(recall_score(y_test, y_test_pred, pos_label=1, zero_division=0), 4)),
            "f1_macro": float(round(f1_score(y_test, y_test_pred, average="macro", zero_division=0), 4)),
            "confusion_matrix": cm_test,  # [[TN, FP], [FN, TP]]
        },
    }
    return metrics


def extract_tree_structure_and_importance(
    fitted_pipeline: Pipeline,
) -> Tuple[str, List[Dict[str, Any]], int, int]:
    """
    Extrae la representación en texto del árbol de decisión ajustado,
    sus características más importantes, su profundidad real y número de hojas.
    """
    preprocessor = fitted_pipeline.named_steps["preprocessor"]
    classifier: DecisionTreeClassifier = fitted_pipeline.named_steps["classifier"]

    # Obtener nombres de características transformadas
    cat_encoder = preprocessor.named_transformers_["cat"]
    cat_feature_names = cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES)
    all_feature_names = list(NUMERIC_FEATURES) + list(cat_feature_names)

    # Reglas en texto
    tree_rules_text = export_text(classifier, feature_names=all_feature_names)

    # Importancia de variables
    importances = classifier.feature_importances_
    features_importance_list = []
    for name, imp in zip(all_feature_names, importances):
        if imp > 0.0:
            features_importance_list.append(
                {"feature": name, "importance": float(round(imp, 4))}
            )
    features_importance_list.sort(key=lambda x: x["importance"], reverse=True)

    tree_depth = int(classifier.get_depth())
    tree_n_leaves = int(classifier.get_n_leaves())

    return tree_rules_text, features_importance_list, tree_depth, tree_n_leaves


def run_pipeline(
    dataset_path: str = DEFAULT_DATASET_PATH,
    output_dir_models: str = MODELS_DIR,
    output_dir_reports: str = REPORTS_DIR,
    random_state: int = 42,
) -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo de principio a fin:
    1. Carga y valida el dataset.
    2. Genera resumen EDA.
    3. Prepara X e y (exclusión de 'Prefiero no responder', binarización).
    4. Realiza partición estratificada 80/20.
    5. Entrena y evalúa Baseline (DummyClassifier).
    6. Entrena y evalúa Árbol de Decisión (DecisionTreeClassifier).
    7. Extrae reglas y métricas.
    8. Serializa artefactos y metadatos verificables.
    """
    os.makedirs(output_dir_models, exist_ok=True)
    os.makedirs(output_dir_reports, exist_ok=True)

    # 1. Carga
    df = load_dataset(dataset_path)
    file_sha256 = compute_file_sha256(dataset_path)

    # 2. EDA
    eda_summary = generate_eda_summary(df)

    # 3. Preparación de X e y
    X, y = prepare_features_and_target(df, target_col=TARGET_COLUMN, filter_uninformative=True)

    # 4. Partición estratificada (80% Train, 20% Test)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=random_state
    )

    # 5. Baseline (Dummy)
    dummy_pipe = build_dummy_baseline_pipeline(strategy="prior", random_state=random_state)
    dummy_metrics = evaluate_pipeline(dummy_pipe, X_train, y_train, X_test, y_test, cv_folds=5)

    # 6. Árbol de decisión
    tree_pipe = build_decision_tree_pipeline(
        max_depth=3,
        min_samples_split=2,
        min_samples_leaf=4,
        class_weight="balanced",
        random_state=random_state,
    )
    tree_metrics = evaluate_pipeline(tree_pipe, X_train, y_train, X_test, y_test, cv_folds=5)

    # 7. Reglas e importancia de variables
    rules_text, feature_importances, depth, n_leaves = extract_tree_structure_and_importance(tree_pipe)

    # 8. Serializar artefactos
    model_filename = "decision_tree_v1.joblib"
    model_path = os.path.join(output_dir_models, model_filename)
    joblib.dump(tree_pipe, model_path)

    import sklearn

    metadata = {
        "model_file": model_filename,
        "model_type": "DecisionTreeClassifier",
        "scikit_learn_version": sklearn.__version__,
        "dataset_path": dataset_path,
        "dataset_sha256": file_sha256,
        "creation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_records_raw": len(df),
        "total_records_filtered": len(X),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "hyperparameters": {
            "max_depth": 3,
            "min_samples_split": 2,
            "min_samples_leaf": 4,
            "class_weight": "balanced",
            "random_state": random_state,
        },
        "tree_characteristics": {
            "actual_depth": depth,
            "number_of_leaves": n_leaves,
            "features_with_positive_importance": len(feature_importances),
        },
    }

    metadata_path = os.path.join(output_dir_models, "model_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    reports_data = {
        "metadata": metadata,
        "tree_metrics": tree_metrics,
        "dummy_baseline_metrics": dummy_metrics,
        "feature_importances": feature_importances,
    }
    metrics_path = os.path.join(output_dir_reports, "ml_01_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(reports_data, f, indent=2, ensure_ascii=False)

    eda_path = os.path.join(output_dir_reports, "eda_summary.json")
    with open(eda_path, "w", encoding="utf-8") as f:
        json.dump(eda_summary, f, indent=2, ensure_ascii=False)

    rules_path = os.path.join(output_dir_reports, "decision_tree_rules.txt")
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write("AFINIA — REGLAS DEL ÁRBOL DE DECISIÓN (DecisionTreeClassifier, depth=3)\n")
        f.write("========================================================================\n\n")
        f.write(rules_text)
        f.write("\n\nIMPORTANCIA DE VARIABLES (Gini Impurity Reduction):\n")
        f.write("---------------------------------------------------\n")
        for fi in feature_importances:
            f.write(f"- {fi['feature']}: {fi['importance']:.4f}\n")

    return reports_data


if __name__ == "__main__":
    print("Ejecutando pipeline analítico ML-01...")
    res = run_pipeline()
    print("Pipeline finalizado con éxito.")
    print("Métricas Árbol (Test):", res["tree_metrics"]["test_set"])
    print("Métricas Dummy (Test):", res["dummy_baseline_metrics"]["test_set"])
