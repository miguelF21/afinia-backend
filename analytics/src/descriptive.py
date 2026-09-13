import pandas as pd
import numpy as np

def generate_descriptive_stats(df: pd.DataFrame, output_file: str):
    """
    Genera un archivo con las estadísticas descriptivas de las variables principales.
    """
    stats = df.describe(include='all').T
    stats.to_csv(output_file)
    print(f"Estadísticas guardadas en {output_file}")

if __name__ == '__main__':
    from load_data import load_raw_data
    from clean_data import clean_data
    import os
    
    raw = load_raw_data("dataset_encuesta.csv")
    df = clean_data(raw)
    
    base_dir = os.path.dirname(os.path.dirname(__file__))
    output_path = os.path.join(base_dir, 'reports', 'estadisticas_descriptivas.csv')
    
    generate_descriptive_stats(df, output_path)
