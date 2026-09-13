import pandas as pd
import numpy as np

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Realiza la limpieza inicial del dataset:
    - Estandariza nombres de columnas.
    - Maneja nulos.
    - Transforma target propuesto (RELACION_SERIA vs OTRA).
    """
    # Hacer copia para no modificar el RAW
    cleaned_df = df.copy()
    
    # Estandarización de nombres
    cleaned_df.columns = [col.strip() for col in cleaned_df.columns]
    
    # Manejo del Target
    target_col = '¿Qué tipo de relación buscas principalmente?'
    if target_col in cleaned_df.columns:
        # Descartar filas que prefieren no responder (para ML)
        cleaned_df = cleaned_df[cleaned_df[target_col] != "Prefiero no responder"]
        
        # Mapear Target Binario
        # 1: Relación seria y estable
        # 0: Otra orientación (Casual, Amistad primero)
        cleaned_df['target'] = np.where(cleaned_df[target_col] == "Una relación seria y estable", 1, 0)
        
        # Opcional: Eliminar columna original del target para evitar redundancia
        cleaned_df = cleaned_df.drop(columns=[target_col])
        
    return cleaned_df

if __name__ == '__main__':
    from load_data import load_raw_data
    try:
        raw_df = load_raw_data("dataset_encuesta.csv")
        clean_df = clean_data(raw_df)
        print(f"Data limpiada: {clean_df.shape}")
        print(f"Distribución del target:\n{clean_df['target'].value_counts(normalize=True)}")
    except Exception as e:
        print(f"No se pudo limpiar la data: {e}")
