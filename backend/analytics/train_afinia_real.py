"""
AFINIA — Pipeline de Machine Learning y Evaluación sobre Afinia.csv (BE-07)
==========================================================================
Evalúa la predicción del tipo de relación buscada (Pregunta 7) utilizando
las variables legítimas del dataset oficial Afinia.csv (105 respuestas).
Compara:
1. DummyClassifier (Baseline mayoritario)
2. DecisionTreeClassifier (depth=3)
3. LogisticRegression (L2)
4. RandomForestClassifier (100 árboles)
Aplica validación cruzada estratificada (5-folds) y split 80/20 estratificado.
"""

import os
import json
import pandas as pd
import numpy as np

from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.dummy import DummyClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    confusion_matrix,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATASET_PATH = os.path.join(BASE_DIR, "data", "raw", "Afinia.csv")


def load_and_preprocess_afinia_dataset(filepath=DATASET_PATH):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"No existe el archivo {filepath}")

    df = pd.read_csv(filepath)

    # 1. Variable objetivo: Pregunta 7
    target_col = [c for c in df.columns if c.startswith("7.")][0]

    # Excluir 'Prefiero no responder' para modelado supervisado legítimo
    mask = df[target_col].astype(str).str.strip() != "Prefiero no responder"
    df_clean = df[mask].copy()

    # Binarización fundamentada:
    # 1: 'Una relación seria y estable'
    # 0: Otra orientación ('Conocer a la persona y ver qué ocurre', 'Actualmente no busco...', 'Depende...', 'Algo casual')
    y = (df_clean[target_col].astype(str).str.strip() == "Una relación seria y estable").astype(int)

    # 2. Columnas numéricas (las 13 características de P8 + P11, P12, P14, P16, P27)
    p8_cols = [c for c in df.columns if c.startswith("8.") and "[" in c]
    p11_col = [c for c in df.columns if c.startswith("11.")][0]
    p12_col = [c for c in df.columns if c.startswith("12.")][0]
    p14_col = [c for c in df.columns if c.startswith("14.")][0]
    p16_col = [c for c in df.columns if c.startswith("16.")][0]
    p27_col = [c for c in df.columns if c.startswith("27.")][0]

    num_cols = p8_cols + [p11_col, p12_col, p14_col, p16_col, p27_col]

    X_num = pd.DataFrame(index=df_clean.index)
    for col in num_cols:
        # Extraer el entero en escalas tipo '4 - Importante' o número directo
        extracted = df_clean[col].astype(str).str.extract(r"(\d+)")[0]
        X_num[col] = extracted.astype(float)

    # 3. Columnas categóricas demográficas y de actitud
    cat_cols = [
        [c for c in df.columns if c.startswith("1.")][0],   # Edad
        [c for c in df.columns if c.startswith("2.")][0],   # Género
        [c for c in df.columns if c.startswith("3.")][0],   # Nivel académico
        [c for c in df.columns if c.startswith("4.")][0],   # Situación sentimental
        [c for c in df.columns if c.startswith("5.")][0],   # Relación previa
        [c for c in df.columns if c.startswith("6.")][0],   # Número novios
        [c for c in df.columns if c.startswith("13.")][0],  # Preferencia personalidad
        [c for c in df.columns if c.startswith("17.")][0],  # Tiempo para decidir
        [c for c in df.columns if c.startswith("18.")][0],  # Pérdida de interés
        [c for c in df.columns if c.startswith("19.")][0],  # Atracción no física
        [c for c in df.columns if c.startswith("20.")][0],  # Experiencias cambiaron
        [c for c in df.columns if c.startswith("28.")][0],  # Revisar redes
        [c for c in df.columns if c.startswith("31.")][0],  # Similares entre sí
        [c for c in df.columns if c.startswith("32.")][0],  # Tipo definido
    ]

    X_cat = df_clean[cat_cols].fillna("Desconocido").astype(str)

    X = pd.concat([X_num, X_cat], axis=1)
    return X, y, num_cols, cat_cols, df_clean


def build_full_preprocessor(num_cols, cat_cols):
    num_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    cat_pipeline = Pipeline([
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    preprocessor = ColumnTransformer([
        ("num", num_pipeline, num_cols),
        ("cat", cat_pipeline, cat_cols),
    ])
    return preprocessor


def evaluate_models(random_state=42):
    X, y, num_cols, cat_cols, df_clean = load_and_preprocess_afinia_dataset()
    preprocessor = build_full_preprocessor(num_cols, cat_cols)

    models = {
        "Dummy (Mayoritario)": DummyClassifier(strategy="prior"),
        "Decision Tree (depth=3)": DecisionTreeClassifier(max_depth=3, min_samples_leaf=4, random_state=random_state),
        "Logistic Regression": LogisticRegression(max_iter=1000, random_state=random_state),
        "Random Forest": RandomForestClassifier(n_estimators=100, max_depth=3, min_samples_leaf=3, random_state=random_state),
    }

    # 1. 5-Fold Stratified Cross Validation sobre la totalidad
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    cv_results_summary = {}

    for name, clf in models.items():
        pipe = Pipeline([("prep", preprocessor), ("clf", clf)])
        cv = cross_validate(
            pipe, X, y, cv=skf,
            scoring=["accuracy", "balanced_accuracy", "f1_macro"]
        )
        cv_results_summary[name] = {
            "accuracy_mean": float(np.round(np.mean(cv["test_accuracy"]), 4)),
            "accuracy_std": float(np.round(np.std(cv["test_accuracy"]), 4)),
            "balanced_accuracy_mean": float(np.round(np.mean(cv["test_balanced_accuracy"]), 4)),
            "balanced_accuracy_std": float(np.round(np.std(cv["test_balanced_accuracy"]), 4)),
            "f1_macro_mean": float(np.round(np.mean(cv["test_f1_macro"]), 4)),
            "f1_macro_std": float(np.round(np.std(cv["test_f1_macro"]), 4)),
        }

    # 2. Split 80/20 estratificado para evaluación de test set
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=random_state
    )

    test_results_summary = {}
    for name, clf in models.items():
        pipe = Pipeline([("prep", preprocessor), ("clf", clf)])
        pipe.fit(X_train, y_train)

        y_pred = pipe.predict(X_test)
        cm = confusion_matrix(y_test, y_pred).tolist()

        test_results_summary[name] = {
            "accuracy": float(np.round(accuracy_score(y_test, y_pred), 4)),
            "balanced_accuracy": float(np.round(balanced_accuracy_score(y_test, y_pred), 4)),
            "precision_class_1": float(np.round(precision_score(y_test, y_pred, pos_label=1, zero_division=0), 4)),
            "recall_class_1": float(np.round(recall_score(y_test, y_pred, pos_label=1, zero_division=0), 4)),
            "precision_class_0": float(np.round(precision_score(y_test, y_pred, pos_label=0, zero_division=0), 4)),
            "recall_class_0": float(np.round(recall_score(y_test, y_pred, pos_label=0, zero_division=0), 4)),
            "f1_macro": float(np.round(f1_score(y_test, y_pred, average="macro", zero_division=0), 4)),
            "confusion_matrix": cm,  # [[TN, FP], [FN, TP]]
        }

    output = {
        "dataset_info": {
            "total_records_raw": 105,
            "total_records_filtered": len(df_clean),
            "target_distribution": {int(k): int(v) for k, v in y.value_counts().items()},
            "train_samples": len(X_train),
            "test_samples": len(X_test),
        },
        "cv_5fold": cv_results_summary,
        "test_evaluation": test_results_summary,
    }

    return output


if __name__ == "__main__":
    results = evaluate_models(random_state=42)
    print("=== RESULTADOS EVALUACIÓN ML (AFINIA.CSV) ===")
    print(json.dumps(results, indent=2))
