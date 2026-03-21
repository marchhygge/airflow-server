from sqlalchemy import create_engine, text
import pandas as pd
import numpy as np
import logging
from sklearn.preprocessing import RobustScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import pickle

log = logging.getLogger(__name__)

def extract_data(engine: create_engine, query: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Executes a SQL query and returns the result as a DataFrame.
    args:
     - engine: SQLAlchemy engine object for database connection
     - query: SQL query string with a placeholder for date
     - start_date: Start date string to replace the placeholder in the query
     - end_date: End date string to replace the placeholder in the query
    returns:
     - pd.DataFrame: DataFrame containing the query results
    raises:
     - Exception: If there is an error executing the query
    """
    try:
        query_resolve = query.format(start_date=start_date, end_date=end_date)
        log.info(f"Executing query: {query_resolve}")
        with engine.connect() as conn:
            result = conn.execute(text(query_resolve))
            df = pd.DataFrame(result)
            return df
    except Exception as e:
        log.error(f"Error executing query. Error: {e}")

def preprocess(df: pd.DataFrame) -> tuple[np.ndarray, RobustScaler]:
    """
    Preprocesses the input DataFrame for KMeans clustering.
    args:
     - df: Input DataFrame containing 'recency' and 'monetary' columns
    returns:
     - tuple[np.ndarray, RobustScaler]: A tuple containing the scaled data and the fitted RobustScaler object
    raises:
     - Exception: If there is an error during preprocessing
     - ValueError: If required columns are missing or if the DataFrame is empty
    """
    try:
        features = df[['recency', 'monetary']].copy()
        features['monetary'] = np.log1p(features['monetary'].astype(float))

        scaler = RobustScaler()
        scaled = scaler.fit_transform(features)
        log.info("\n" + "Scaler:" + "\n" + pd.DataFrame(scaler.scale_).head(10).to_markdown(index=False))
        log.info("\n" + "Scaled data:" + "\n" + pd.DataFrame(scaled).head(10).to_markdown(index=False))
        return scaled, scaler
    except KeyError as e:
        log.error(f"Missing required column: {str(e)}")
        raise ValueError(f"Missing required column: {str(e)}")
    except Exception as e:
        log.error(f"Error during preprocessing. Error: {e}")
        raise Exception(f"Error during preprocessing. Error: {e}")

def find_k(scaled_data: np.ndarray, k_range=range(2,8)):
    """
    finds the optimal number of clusters (k) for KMeans using silhouette score.
    args:
    - scaled_data: Scaled data to be clustered
    - k_range: Range of k values to evaluate (default: 2 to 7)
    returns:
    - None: This function prints the silhouette scores for each k but does not return any value
    raises:
    - Exception: If there is an error during the process
    """
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42)
        lbl = km.fit_predict(scaled_data)
        sil = silhouette_score(scaled_data, lbl)
        log.info(f'k={k} | inertia={km.inertia_: ,.1f} | silhouette={sil: .4f}')

def train_KMeans(scaled_data: np.ndarray, n_clusters: int = 3) -> KMeans:
    """
    Trains a KMeans model on the scaled data.
    args:
    - scaled_data: Scaled data to be clustered
    - n_clusters: Number of clusters to form (default: 3)
    returns:
    - KMeans: The trained KMeans model
    """
    km = KMeans(n_clusters=n_clusters, random_state=42)
    km.fit(scaled_data)
    log.info(f'KMeans trained with n_clusters={n_clusters} | inertia={km.inertia_: ,.1f}')
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
    centroid_df['r_rank'] = centroid_df['recency'].rank(ascending=True)
    centroid_df['m_rank'] = centroid_df['monetary'].rank(ascending=False)

    # Assign labels
    label_map = {}
    for _, row in centroid_df.iterrows():

        if row['r_rank'] <= 2 and row['m_rank'] == 1:
            label = 'champions'
        elif row['r_rank'] <= 2 and row['m_rank'] != 1:
            label = 'potential'
        else:
            label = 'at_risk'

        label_map[int(row['cluster'])] = label

    log.info("\n=== Cluster centroid ===")
    log.info("\n" + centroid_df[['cluster', 'recency', 'monetary']].to_string(index=False))
    log.info(f"labels: {label_map}")
    return label_map

def save_artifacts(engine: create_engine, artifacts_name: str, obj, artifact_query: str) -> None:
    data = pickle.dumps(obj)
    with engine.begin() as conn:
        conn.execute(text(artifact_query), {
            "artifact_name": artifacts_name,
            "artifact_data": data,
            "updated_at": pd.Timestamp.now()
        })
    log.info(f"Saved artifact: {artifacts_name} to database")

def save_rfm_clusters(schema: str, table_name: str, df: pd.DataFrame, km: KMeans, label_map: dict, engine: create_engine):
    result = df[['customer_unique_id', 'recency', 'monetary']].copy()
    result['cluster_id'] = km.labels_ 
    result['cluster_name'] = result['cluster_id'].map(label_map)
    result['updated_at'] = pd.Timestamp.now()
    log.info("\n" + "Clustered data sample:" + "\n" + result.head(10).to_markdown(index=False))
    result.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists='replace',
        index=False
    )
    log.info(f"saved {len(result)} records to {schema}.{table_name}")