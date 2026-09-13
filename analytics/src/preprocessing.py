import pandas as pd
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer

def get_preprocessor(df: pd.DataFrame):
    """
    Construye el preprocesador para el modelo de ML en base a las columnas.
    """
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
    numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns.tolist()
    
    if 'target' in numeric_cols:
        numeric_cols.remove('target')

    # Para variables categóricas nominales
    categorical_transformer = OneHotEncoder(handle_unknown='ignore')
    
    # Para variables numéricas / ordinales (ya codificadas como 1-5)
    numeric_transformer = StandardScaler()
    
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numeric_transformer, numeric_cols),
            ('cat', categorical_transformer, categorical_cols)
        ]
    )
    
    return preprocessor

if __name__ == '__main__':
    from load_data import load_raw_data
    from clean_data import clean_data
    
    df = load_raw_data()
    clean_df = clean_data(df)
    prep = get_preprocessor(clean_df.drop(columns=['target']))
    print("Preprocesador configurado:\n", prep)
