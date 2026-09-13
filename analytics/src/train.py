import pandas as pd
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import classification_report, accuracy_score

from sklearn.pipeline import Pipeline

def train_baselines(X, y, preprocessor):
    """
    Entrena los modelos iniciales con validación cruzada estratificada (K=5).
    Modelos:
    - Dummy (Baseline 0)
    - Regresión Logística (Modelo 1)
    - Árbol de Decisión (Modelo 2)
    """
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    
    models = {
        'Dummy (Baseline)': DummyClassifier(strategy='prior'),
        'Logistic Regression': LogisticRegression(random_state=42, max_iter=1000),
        'Decision Tree': DecisionTreeClassifier(random_state=42, max_depth=4, min_samples_leaf=5)
    }
    
    results = {}
    
    for name, model in models.items():
        # Crear pipeline completo
        clf = Pipeline(steps=[('preprocessor', preprocessor),
                              ('classifier', model)])
                              
        # Evaluamos usando CV
        cv_results = cross_validate(clf, X, y, cv=skf, scoring=['accuracy', 'precision', 'recall', 'f1_macro'])
        results[name] = cv_results
        
        print(f"--- {name} ---")
        print(f"Accuracy: {cv_results['test_accuracy'].mean():.4f} (+/- {cv_results['test_accuracy'].std() * 2:.4f})")
        print(f"F1 (Macro): {cv_results['test_f1_macro'].mean():.4f}")
        print("-" * 20)
        
    return results

if __name__ == '__main__':
    from load_data import load_raw_data
    from clean_data import clean_data
    from preprocessing import get_preprocessor
    
    # 1. Cargar datos
    raw = load_raw_data("dataset_encuesta.csv")
    
    # 2. Limpiar
    df = clean_data(raw)
    
    # 3. Separar X e y
    X = df.drop(columns=['target'])
    y = df['target']
    
    # 4. Obtener preprocesador
    prep = get_preprocessor(X)
    
    # 5. Entrenar baselines
    print("Iniciando entrenamiento base...")
    train_baselines(X, y, prep)
