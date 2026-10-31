import pandas as pd
import numpy as np
import os
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# Configurar rutas
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
MODELS_DIR = os.path.join(BASE_DIR, 'models')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# 1. Generar Dataset Sintético
def generate_synthetic_data(num_samples=2000):
    np.random.seed(42)
    
    # Rasgos de personalidad (Big 5) normalizados de 0 a 10
    features = ['extroversion', 'openness', 'agreeableness', 'conscientiousness', 'neuroticism']
    
    data = []
    for _ in range(num_samples):
        user_a = {f"user_a_{f}": np.random.randint(1, 11) for f in features}
        user_b = {f"user_b_{f}": np.random.randint(1, 11) for f in features}
        
        # Lógica sintética de compatibilidad
        # Extrovertidos se llevan bien con extrovertidos, etc. 
        # Diferencia baja en openness y agreeableness incrementa la probabilidad
        diff_openness = abs(user_a['user_a_openness'] - user_b['user_b_openness'])
        diff_agree = abs(user_a['user_a_agreeableness'] - user_b['user_b_agreeableness'])
        diff_extro = abs(user_a['user_a_extroversion'] - user_b['user_b_extroversion'])
        
        # Una penalización basada en diferencias
        penalty = diff_openness + diff_agree + diff_extro
        
        # Probabilidad base
        prob_match = 0.8 - (penalty * 0.03)
        prob_match = np.clip(prob_match, 0.1, 0.9)
        
        # Clase objetivo (1 = Match Exitoso, 0 = No Match)
        is_match = np.random.binomial(1, prob_match)
        
        row = {**user_a, **user_b, 'is_match': is_match}
        data.append(row)
        
    df = pd.DataFrame(data)
    csv_path = os.path.join(DATA_DIR, 'synthetic_matches.csv')
    df.to_csv(csv_path, index=False)
    print(f"Dataset generado con {num_samples} registros en: {csv_path}")
    return df

# 2. Entrenar Modelo
def train_model(df):
    X = df.drop(columns=['is_match'])
    y = df['is_match']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Entrenar un RandomForest simple pero efectivo para el MVP
    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    clf.fit(X_train, y_train)
    
    # Evaluar
    y_pred = clf.predict(X_test)
    print("Reporte de Clasificación:")
    print(classification_report(y_test, y_pred))
    
    # 3. Exportar Modelo
    model_path = os.path.join(MODELS_DIR, 'afinia_model_v1.pkl')
    joblib.dump(clf, model_path)
    print(f"Modelo guardado exitosamente en: {model_path}")

if __name__ == "__main__":
    print("Iniciando pipeline de Machine Learning...")
    df = generate_synthetic_data()
    train_model(df)
