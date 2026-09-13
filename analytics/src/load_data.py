import pandas as pd
import os

def load_raw_data(filename="dataset_encuesta.csv"):
    """
    Carga el dataset de respuestas en crudo de Google Forms.
    Asume que el archivo está en la ruta afinia/data/raw/
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    file_path = os.path.join(base_dir, 'data', 'raw', filename)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"El archivo {file_path} no existe. Por favor, asegúrese de guardar el CSV exportado en data/raw/.")
        
    df = pd.read_csv(file_path)
    return df

if __name__ == '__main__':
    try:
        df = load_raw_data()
        print(f"Dataset cargado exitosamente. Shape: {df.shape}")
    except FileNotFoundError as e:
        print(e)
