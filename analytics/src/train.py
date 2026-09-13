import pandas as pd
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import classification_report, accuracy_score

def train_baselines(X, y):
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
        # Evaluamos usando CV
        cv_results = cross_validate(model, X, y, cv=skf, scoring=['accuracy', 'precision', 'recall', 'f1_macro'])
        results[name] = cv_results
        
        print(f"--- {name} ---")
        print(f"Accuracy: {cv_results['test_accuracy'].mean():.4f} (+/- {cv_results['test_accuracy'].std() * 2:.4f})")
        print(f"F1 (Macro): {cv_results['test_f1_macro'].mean():.4f}")
        print("-" * 20)
        
    return results

if __name__ == '__main__':
    print("Módulo de entrenamiento base. Esperando X, y.")
