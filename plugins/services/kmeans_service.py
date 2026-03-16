from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from os import getenv
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import logging
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from supabase import create_client
import pickle

log = logging.getLogger(__name__)

def build_engine() -> create_engine:
    try:
        engine = create_engine(f'postgresql://{user}:{password}@{host}:{port}/{database}')
        log.info(f"successfully created engine for database: {database}")
        return engine
    except Exception as e:
        log.error(f"Error creating engine. Error: {e}")

def extract_data(engine: create_engine, query: str, execute_date: str) -> pd.DataFrame:
    try:
        query_resolve = query.format(date=execute_date)
        with engine.connect() as conn:
            result = conn.execute(text(query_resolve))
            df = pd.DataFrame(result)
            return df
    except Exception as e:
        log.error(f"Error executing query. Error: {e}")

def preprocess(df: pd.DataFrame) -> tuple[np.ndarray, RobustScaler]:
    features = df[['recency', 'monetary']].copy()
    features['monetary'] = np.log1p(features['monetary'].astype(float))

    scaler = RobustScaler()
    scaled = scaler.fit_transform(features)
    return scaled, scaler

def find_k(scaled_data: np.ndarray, k_range=range(2,8)):
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42)
        lbl = km.fit_predict(scaled_data)
        sil = silhouette_score(scaled_data, lbl)
        print(f'k={k} | inertia={km.inertia_: ,.1f} | silhouette={sil: .4f}')

def train_KMeans(scaled_data: np.ndarray, n_clusters: int = 3) -> KMeans:
    km = KMeans(n_clusters=n_clusters, random_state=42)
    km.fit(scaled_data)
    print(f'KMeans trained with n_clusters={n_clusters} | inertia={km.inertia_: ,.1f}')
    return km

def label_clusters(km: KMeans, scaler: RobustScaler) -> dict:
    # Inverse transform
    centroids_orig= scaler.inverse_transform(km.cluster_centers_)

    # Create a DataFrame for centroids
    centroid_df = pd.DataFrame({
        'cluster': range(len(centroids_orig)),
        'recency': centroids_orig[:, 0],
        'monetary': centroids_orig[:, 1]
    })

    # Reverse log1p
    centroid_df['monetary'] = np.expm1(centroid_df['monetary'])

    # Define labels based on centroids
    med_r = centroid_df['recency'].median()
    med_m = centroid_df['monetary'].median()

    # Assign labels 
    label_map = {}
    for _, row in centroid_df.iterrows():
        is_recent = row['recency'] < med_r
        is_high_value = row['monetary'] > med_m

        if is_recent and is_high_value: 
            label = 'champions'
        elif is_recent and not is_high_value:
            label = 'potential'
        else:
            label = 'at_risk'

        label_map[int(row['cluster'])] = label

    log.info("\n=== Cluster centroid ===")
    log.info("\n" + centroid_df[['cluster', 'recency', 'monetary']].to_string(index=False))
    log.info("labels:", label_map)
    return label_map

def save_artifacts(bucket: str, km: KMeans, scaler: RobustScaler, label_map: dict):
    supabase = create_client(supabase_url, supabase_key)
    artifacts = {
        'rfm/kmeans.pkl': pickle.dumps(km),
        'rfm/scaler.pkl': pickle.dumps(scaler),
    }
    for path, data in artifacts.items():
        supabase.storage.from_(bucket).upload(
            path, 
            file=data,
            file_options={"upsert": "true", "content_type": "application/octet-stream"}
        )
        log.info(f"Saved artifact: {path}")

def save_rfm_clusters(schema: str, table_name: str, df: pd.DataFrame, km: KMeans, label_map: dict, engine: create_engine):
    result = df[['customer_unique_id', 'recency', 'monetary']].copy()
    result['cluster_id'] = km.labels_ 
    result['cluster_name'] = result['cluster_id'].map(label_map)
    result['updated_at'] = pd.Timestamp.now()
    result.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists='replace',
        index=False
    )
    log.info(f"saved {len(result)} records to {schema}.{table_name}")