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
    
    # Aquí irá la estandarización de columnas cuando tengamos el CSV real
    # Ejemplo genérico: cleaned_df.columns = [col.lower().replace(' ', '_') for col in cleaned_df.columns]
    
    # En las instrucciones se propone aislar el target (¿Qué tipo de relación buscas principalmente?)
    # Transformación binaria tentativa
    # RELACION_SERIA (Si contiene "Una relación seria y estable")
    # OTRA_ORIENTACION (El resto)
    # Excluyendo explícitamente "Prefiero no responder"
    
    return cleaned_df

if __name__ == '__main__':
    from load_data import load_raw_data
    try:
        raw_df = load_raw_data()
        clean_df = clean_data(raw_df)
        print(f"Data limpiada: {clean_df.shape}")
    except Exception as e:
        print(f"No se pudo limpiar la data: {e}")
