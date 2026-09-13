import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
import joblib
import os

def export_model(X, y, preprocessor, output_path):
    """
    Entrena el modelo final (Logistic Regression) en todo el dataset y lo exporta.
    """
    model = LogisticRegression(random_state=42, max_iter=1000)
    
    clf = Pipeline(steps=[('preprocessor', preprocessor),
                          ('classifier', model)])
                          
    clf.fit(X, y)
    
    joblib.dump(clf, output_path)
    print(f"Modelo exportado exitosamente a {output_path}")

if __name__ == '__main__':
    from load_data import load_raw_data
    from clean_data import clean_data
    from preprocessing import get_preprocessor
    
    raw = load_raw_data("dataset_encuesta.csv")
    df = clean_data(raw)
    
    X = df.drop(columns=['target'])
    y = df['target']
    
    prep = get_preprocessor(X)
    
    base_dir = os.path.dirname(os.path.dirname(__file__))
    model_path = os.path.join(base_dir, 'models', 'afinia_model_v1.pkl')
    
    export_model(X, y, prep, model_path)
