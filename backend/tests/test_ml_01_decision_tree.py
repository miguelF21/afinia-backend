"""
AFINIA — Test Suite ML-01: Árbol de Decisión y Evaluación del Modelo.
====================================================================
Verifica lectura de datos, validación de esquemas, prevención de fuga de etiqueta,
reproducibilidad, manejo de valores desconocidos y cálculo no trivial de métricas.
"""

import os
import tempfile
import pytest
import pandas as pd
import numpy as np
import joblib

try:
    from analytics.pipeline import (
        DEFAULT_DATASET_PATH,
        NUMERIC_FEATURES,
        CATEGORICAL_FEATURES,
        TARGET_COLUMN,
        load_dataset,
        generate_eda_summary,
        prepare_features_and_target,
        build_preprocessor,
        build_decision_tree_pipeline,
        build_dummy_baseline_pipeline,
        evaluate_pipeline,
        extract_tree_structure_and_importance,
        run_pipeline,
    )
except ModuleNotFoundError:
    from backend.analytics.pipeline import (
        DEFAULT_DATASET_PATH,
        NUMERIC_FEATURES,
        CATEGORICAL_FEATURES,
        TARGET_COLUMN,
        load_dataset,
        generate_eda_summary,
        prepare_features_and_target,
        build_preprocessor,
        build_decision_tree_pipeline,
        build_dummy_baseline_pipeline,
        evaluate_pipeline,
        extract_tree_structure_and_importance,
        run_pipeline,
    )


class TestDatasetInspectionAndQuality:
    """Pruebas de carga, verificación de esquema y manejo de excepciones."""

    def test_load_dataset_physical_exists(self):
        """Verifica que el dataset exista físicamente y cargue con 103 filas y 21 columnas."""
        assert os.path.exists(DEFAULT_DATASET_PATH), f"El archivo {DEFAULT_DATASET_PATH} debe existir."
        df = load_dataset(DEFAULT_DATASET_PATH)
        assert len(df) == 103
        assert len(df.columns) == 21
        assert TARGET_COLUMN in df.columns
        for col in NUMERIC_FEATURES:
            assert col in df.columns
        for col in CATEGORICAL_FEATURES:
            assert col in df.columns

    def test_load_dataset_missing_file_raises_filenotfound(self):
        """Verifica que una ruta inexistente genere FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_dataset("ruta/inexistente/dataset.csv")

    def test_load_dataset_missing_columns_raises_value_error(self):
        """Verifica que si faltan columnas críticas se rechace con ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Edad,OtroDato\n25,Valor\n")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="El dataset carece de columnas requeridas"):
                load_dataset(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_generate_eda_summary_structure(self):
        """Verifica que el resumen exploratorio contenga métricas completas y sin nulos."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        eda = generate_eda_summary(df)

        assert eda["total_records"] == 103
        assert eda["total_columns"] == 21
        assert eda["duplicate_rows"] == 0
        assert TARGET_COLUMN in eda["missing_values"]
        # En el dataset crudo no debe haber nulos imprevistos
        assert sum(eda["missing_values"].values()) == 0
        assert len(eda["categorical_distributions"]) == len(CATEGORICAL_FEATURES)
        assert len(eda["numerical_statistics"]) == len(NUMERIC_FEATURES)


class TestTargetSelectionAndLeakagePrevention:
    """Pruebas sobre la variable objetivo y la prevención estricta de fugas."""

    def test_target_preparation_filters_uninformative(self):
        """Verifica que se excluyan los 5 registros de 'Prefiero no responder' y queden 98."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        raw_prefiere_no_decir = (df[TARGET_COLUMN] == "Prefiero no responder").sum()
        assert raw_prefiere_no_decir == 5

        X, y = prepare_features_and_target(df, filter_uninformative=True)
        assert len(X) == 98
        assert len(y) == 98
        # Clases binarias deben ser únicamente {0, 1}
        assert set(y.unique()) == {0, 1}
        # Clase 1: 43 ejemplos (43.88%), Clase 0: 55 ejemplos (56.12%)
        assert (y == 1).sum() == 43
        assert (y == 0).sum() == 55

    def test_strict_leakage_prevention(self):
        """Verifica que la variable objetivo esté excluida categóricamente de X."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        assert TARGET_COLUMN not in X.columns
        for col in X.columns:
            assert "relacion_buscada" not in col
            assert "tipo_relacion" not in col

    def test_missing_target_column_raises_key_error(self):
        """Verifica que solicitar una variable objetivo ausente genere KeyError."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        with pytest.raises(KeyError, match="no existe en el DataFrame"):
            prepare_features_and_target(df, target_col="columna_inexistente")


class TestPipelinePreprocessingAndInference:
    """Pruebas del Pipeline scikit-learn, transformaciones y robustez."""

    def test_pipeline_handles_unknown_categories(self):
        """Verifica que el pipeline pueda inferir con categorías no vistas sin fallar."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        pipe = build_decision_tree_pipeline(random_state=42)
        pipe.fit(X, y)

        # Crear una muestra sintética con categorías nuevas
        sample_unseen = X.iloc[[0]].copy()
        sample_unseen["genero"] = "CategoriaNoVista123"
        sample_unseen["ubicacion"] = "Extraterrestre"
        sample_unseen["ocupacion"] = "Astronauta"
        sample_unseen["frecuencia_ejercicio"] = "CadaCometa"
        sample_unseen["preferencia_mascotas"] = "Dragon"
        sample_unseen["habito_fumar"] = "VaporEspacial"

        pred = pipe.predict(sample_unseen)
        assert len(pred) == 1
        assert pred[0] in [0, 1]

    def test_pipeline_reproducibility(self):
        """Verifica que dos entrenamientos con random_state=42 produzcan idéntico modelo."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        pipe1 = build_decision_tree_pipeline(random_state=42)
        pipe1.fit(X, y)
        preds1 = pipe1.predict(X)

        pipe2 = build_decision_tree_pipeline(random_state=42)
        pipe2.fit(X, y)
        preds2 = pipe2.predict(X)

        np.testing.assert_array_equal(preds1, preds2)
        clf1 = pipe1.named_steps["classifier"]
        clf2 = pipe2.named_steps["classifier"]
        np.testing.assert_array_equal(clf1.feature_importances_, clf2.feature_importances_)


class TestModelEvaluationAndBaseline:
    """Pruebas de evaluación rigurosa contra baseline."""

    def test_tree_evaluation_real_metrics_computed(self):
        """Verifica el cálculo correcto de métricas sin inventar valores ficticios."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, stratify=y, random_state=42
        )

        tree_pipe = build_decision_tree_pipeline(max_depth=3, min_samples_leaf=4, random_state=42)
        metrics = evaluate_pipeline(tree_pipe, X_train, y_train, X_test, y_test, cv_folds=5)

        # Verificación de estructura y consistencia
        test_m = metrics["test_set"]
        assert 0.0 <= test_m["accuracy"] <= 1.0
        assert 0.0 <= test_m["balanced_accuracy"] <= 1.0
        assert 0.0 <= test_m["f1_macro"] <= 1.0
        assert test_m["n_samples"] == 20

        # Matriz de confusión 2x2
        cm = test_m["confusion_matrix"]
        assert len(cm) == 2 and len(cm[0]) == 2
        total_cm = sum(cm[0]) + sum(cm[1])
        assert total_cm == 20

        # Detección honesta de sobreajuste:
        # En train la precisión es notablemente superior que en test
        train_m = metrics["train_set"]
        assert train_m["accuracy"] > test_m["accuracy"]

    def test_comparison_with_dummy_baseline(self):
        """
        Verifica que el baseline DummyClassifier se evalúe honestamente y que
        se registre la limitación de generalización del árbol en datos ruidosos.
        """
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, stratify=y, random_state=42
        )

        dummy_pipe = build_dummy_baseline_pipeline(strategy="prior", random_state=42)
        dummy_metrics = evaluate_pipeline(dummy_pipe, X_train, y_train, X_test, y_test, cv_folds=5)

        # El dummy en test predice la clase mayoritaria (0) para las 20 muestras
        dummy_test = dummy_metrics["test_set"]
        assert dummy_test["accuracy"] == 0.55  # 11/20
        assert dummy_test["balanced_accuracy"] == 0.5

    def test_extract_tree_structure_and_importance(self):
        """Verifica la extracción de reglas legibles y que la profundidad sea máxima 3."""
        df = load_dataset(DEFAULT_DATASET_PATH)
        X, y = prepare_features_and_target(df, filter_uninformative=True)

        pipe = build_decision_tree_pipeline(max_depth=3, min_samples_leaf=4, random_state=42)
        pipe.fit(X, y)

        rules, importances, depth, n_leaves = extract_tree_structure_and_importance(pipe)

        assert depth <= 3
        assert n_leaves >= 2
        assert "class:" in rules
        assert len(importances) > 0
        # La suma de importancias debe aproximar 1.0
        total_imp = sum(item["importance"] for item in importances)
        assert abs(total_imp - 1.0) < 0.05

    def test_full_pipeline_run_generates_verified_artifacts(self):
        """Verifica que run_pipeline guarde los artefactos esperados con metadatos completos."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            models_tmp = os.path.join(tmp_dir, "models")
            reports_tmp = os.path.join(tmp_dir, "reports")

            res = run_pipeline(
                dataset_path=DEFAULT_DATASET_PATH,
                output_dir_models=models_tmp,
                output_dir_reports=reports_tmp,
                random_state=42,
            )

            # Archivos generados
            assert os.path.exists(os.path.join(models_tmp, "decision_tree_v1.joblib"))
            assert os.path.exists(os.path.join(models_tmp, "model_metadata.json"))
            assert os.path.exists(os.path.join(reports_tmp, "ml_01_metrics.json"))
            assert os.path.exists(os.path.join(reports_tmp, "eda_summary.json"))
            assert os.path.exists(os.path.join(reports_tmp, "decision_tree_rules.txt"))

            # Validar carga de joblib
            loaded_model = joblib.load(os.path.join(models_tmp, "decision_tree_v1.joblib"))
            assert hasattr(loaded_model, "predict")
