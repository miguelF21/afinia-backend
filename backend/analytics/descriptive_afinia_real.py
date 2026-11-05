"""
AFINIA — Análisis Descriptivo y Segmentación no supervisada (BE-07)
==================================================================
Analiza las respuestas reales de Afinia.csv:
1. Rankings y estadísticas de las 13 características valoradas (P8).
2. Distribución de objetivos relacionales (P7).
3. Análisis de P9 (Top 3), P11 (gustos), P12 (valores), P13 (personalidad), P14 (metas).
4. Segmentación exploratoria no supervisada (KMeans, k=3) sobre las 13 características.
5. Generación de informes en JSON y tablas descriptivas.
"""

import os
import json
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(BASE_DIR, "data", "raw", "Afinia.csv")
REPORTS_DIR = os.path.join(BASE_DIR, "analytics", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def run_descriptive_analysis():
    df = pd.read_csv(CSV_PATH)

    # 1. Columnas P8 (13 características)
    p8_cols = [c for c in df.columns if c.startswith("8.") and "[" in c]
    p8_labels = [c.split("[")[-1].replace("]", "").strip() for c in p8_cols]

    p8_df = pd.DataFrame(index=df.index)
    for orig, label in zip(p8_cols, p8_labels):
        p8_df[label] = df[orig].astype(str).str.extract(r"(\d+)")[0].astype(float)

    # Estadísticas P8
    p8_stats = []
    for label in p8_labels:
        s = p8_df[label]
        p8_stats.append({
            "caracteristica": label,
            "media": float(np.round(s.mean(), 2)),
            "desviacion": float(np.round(s.std(), 2)),
            "mediana": float(s.median()),
            "pct_muy_importante": float(np.round((s == 5).mean() * 100, 1)),
            "pct_importante_o_mas": float(np.round((s >= 4).mean() * 100, 1)),
        })
    p8_stats.sort(key=lambda x: x["media"], reverse=True)

    # 2. Distribución P7 (Tipo de relación buscada)
    p7_col = [c for c in df.columns if c.startswith("7.")][0]
    p7_dist = df[p7_col].value_counts().to_dict()

    # 3. Preguntas 11, 12, 14 (escalas de compatibilidad 1-5)
    p11_col = [c for c in df.columns if c.startswith("11.")][0]
    p12_col = [c for c in df.columns if c.startswith("12.")][0]
    p14_col = [c for c in df.columns if c.startswith("14.")][0]

    scales_summary = {
        "gustos_intereses_similares_P11": {
            "media": float(np.round(df[p11_col].astype(float).mean(), 2)),
            "distribucion": {str(k): int(v) for k, v in df[p11_col].value_counts().to_dict().items()}
        },
        "valores_principios_similares_P12": {
            "media": float(np.round(df[p12_col].astype(float).mean(), 2)),
            "distribucion": {str(k): int(v) for k, v in df[p12_col].value_counts().to_dict().items()}
        },
        "metas_vida_compatibles_P14": {
            "media": float(np.round(df[p14_col].astype(float).mean(), 2)),
            "distribucion": {str(k): int(v) for k, v in df[p14_col].value_counts().to_dict().items()}
        }
    }

    # 4. Pregunta 13: Preferencia de personalidad
    p13_col = [c for c in df.columns if c.startswith("13.")][0]
    p13_dist = df[p13_col].value_counts().to_dict()

    # 5. Segmentación exploratoria no supervisada (KMeans, k=3)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(p8_df)
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)
    p8_df["cluster"] = clusters

    cluster_profiles = {}
    for c_id in range(3):
        c_sub = p8_df[p8_df["cluster"] == c_id].drop(columns=["cluster"])
        cluster_profiles[f"Cluster_{c_id}"] = {
            "num_encuestados": int(len(c_sub)),
            "porcentaje": float(np.round(len(c_sub) / len(df) * 100, 1)),
            "medias": {k: float(np.round(v, 2)) for k, v in c_sub.mean().to_dict().items()}
        }

    report = {
        "dataset": "Afinia.csv (Encuesta real académica)",
        "total_respuestas": len(df),
        "ranking_13_caracteristicas_P8": p8_stats,
        "distribucion_tipo_relacion_P7": p7_dist,
        "escalas_compatibilidad_P11_P12_P14": scales_summary,
        "preferencia_personalidad_P13": p13_dist,
        "segmentacion_exploratoria_kmeans_3": cluster_profiles,
        "advertencia_metodologica": (
            "Los clusters representan agrupaciones exploratorias de prioridades declaradas "
            "y NO constituyen perfiles psicológicos o diagnósticos clínicos."
        )
    }

    out_path = os.path.join(REPORTS_DIR, "afinia_real_descriptive.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Reporte descriptivo generado exitosamente en: {out_path}")
    return report


if __name__ == "__main__":
    rep = run_descriptive_analysis()
    print("\n--- TOP 5 CARACTERÍSTICAS MÁS VALORADAS ---")
    for item in rep["ranking_13_caracteristicas_P8"][:5]:
        print(f" {item['caracteristica']:25s} | Media: {item['media']:.2f} | % >= 4: {item['pct_importante_o_mas']}%")

    print("\n--- CARACTERÍSTICAS MENOS VALORADAS EN LA MUESTRA ---")
    for item in rep["ranking_13_caracteristicas_P8"][-3:]:
        print(f" {item['caracteristica']:25s} | Media: {item['media']:.2f} | % >= 4: {item['pct_importante_o_mas']}%")
