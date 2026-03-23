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
        raise

def preprocess(df: pd.DataFrame) -> tuple[np.ndarray, RobustScaler]:
    """
    Preprocesses the input DataFrame for KMeans clustering.
    args:
     - df: Input DataFrame containing 'recency', 'frequency', and 'monetary' columns
    returns:
     - tuple[np.ndarray, RobustScaler]: A tuple containing the scaled data and the fitted RobustScaler object
    raises:
     - Exception: If there is an error during preprocessing
     - ValueError: If required columns are missing or if the DataFrame is empty
    """
    try:
        features = df[['recency', 'frequency', 'monetary']].copy()
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
    centroids_orig = scaler.inverse_transform(km.cluster_centers_)

    # Create a DataFrame for centroids
    centroid_df = pd.DataFrame({
        'cluster':   range(len(centroids_orig)),
        'recency':   centroids_orig[:, 0],
        'frequency': centroids_orig[:, 1],
        'monetary':  centroids_orig[:, 2]
    })

    # Reverse log1p on monetary only
    centroid_df['monetary'] = np.expm1(centroid_df['monetary'])

    # Rank each dimension
    centroid_df['r_rank'] = centroid_df['recency'].rank(ascending=True)    # low days = good
    centroid_df['f_rank'] = centroid_df['frequency'].rank(ascending=False) # high freq = good
    centroid_df['m_rank'] = centroid_df['monetary'].rank(ascending=False)  # high spend = good

    # Assign labels
    label_map = {}
    for _, row in centroid_df.iterrows():
        if row['r_rank'] <= 2 and row['f_rank'] == 1 and row['m_rank'] == 1:
            label = 'champions'
        elif row['r_rank'] <= 2:
            label = 'potential'
        else:
            label = 'at_risk'
        label_map[int(row['cluster'])] = label

    log.info("\n=== Cluster centroid ===" + "\n" + centroid_df[['cluster', 'recency', 'frequency', 'monetary']].to_string(index=False))
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

def save_rfm_clusters(schema: str, table_name: str, df: pd.DataFrame, km: KMeans, label_map: dict, engine: create_engine,
                      labels: np.ndarray = None, if_exists: str = 'replace', execution_date=None) -> int:
    result = df[['customer_unique_id', 'recency', 'frequency', 'monetary']].copy()
    result['cluster_id'] = labels if labels is not None else km.labels_
    result['cluster_name'] = result['cluster_id'].map(label_map)
    result['updated_at'] = pd.Timestamp.now()
    if execution_date is not None:
        result['execution_date'] = execution_date
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {schema}.{table_name} WHERE execution_date = :execution_date"),
                         {"execution_date": execution_date})
        log.info(f"Deleted existing records for execution_date={execution_date} from {schema}.{table_name}")
    log.info("\n" + "Clustered data sample:" + "\n" + result.head(10).to_markdown(index=False))
    result.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists=if_exists,
        index=False
    )
    n_samples = len(result)
    log.info(f"saved {n_samples} records to {schema}.{table_name}")
    return n_samples

def save_training_metadata(engine: create_engine, km: KMeans, scaler: RobustScaler, scaled_data: np.ndarray,
                           query: str, start_date: str, end_date: str, n_samples: int):
    sil = silhouette_score(scaled_data, km.labels_)
    with engine.begin() as conn:
        result = conn.execute(text(query),
        {
            "trained_at": pd.Timestamp.now(),
            "start_date": start_date,
            "end_date": end_date,
            "n_samples": n_samples,
            "n_clusters": km.n_clusters,
            "inertia": km.inertia_,
            "silhouette": float(sil),
            "n_iter": km.n_iter_,
            # scaler.center_ = [recency_median, frequency_median, monetary_median]
            "recency_median":   float(scaler.center_[0]),
            "frequency_median": float(scaler.center_[1]),
            "monetary_median":  float(scaler.center_[2]),
            # scaler.scale_ = [recency_iqr, frequency_iqr, monetary_iqr]
            "recency_iqr":   float(scaler.scale_[0]),
            "frequency_iqr": float(scaler.scale_[1]),
            "monetary_iqr":  float(scaler.scale_[2])
        })
        training_id = result.fetchone()[0] # get the generated training_id

    log.info(f"Saved training metadata to database: training_id={training_id} |"
            f"silhouette={sil:.4f} | inertia={km.inertia_:,.1f} | "
            f"recency_median={scaler.center_[0]:.2f} | recency_iqr={scaler.scale_[0]:.2f} | "
            f"frequency_median={scaler.center_[1]:.2f} | frequency_iqr={scaler.scale_[1]:.2f} | "
            f"monetary_median={scaler.center_[2]:.2f} | monetary_iqr={scaler.scale_[2]:.2f}")
    return training_id

def save_centroid_metadata(engine: create_engine, km: KMeans, scaler: RobustScaler, query: str,
                           training_id: int, label_map: dict) -> None:
    centroids_orig = scaler.inverse_transform(km.cluster_centers_)
    records = []
    for cluster_id in range(len(km.cluster_centers_)):
        records.append({
            "training_id":      training_id,
            "cluster_id":       cluster_id,
            "cluster_name":     label_map[cluster_id],
            "recency_scaled":   float(km.cluster_centers_[cluster_id][0]),
            "frequency_scaled": float(km.cluster_centers_[cluster_id][1]),
            "monetary_scaled":  float(km.cluster_centers_[cluster_id][2]),
            "recency_orig":     float(centroids_orig[cluster_id][0]),
            "frequency_orig":   float(centroids_orig[cluster_id][1]),
            "monetary_orig":    float(np.expm1(centroids_orig[cluster_id][2]))
        })
    with engine.begin() as conn:
        conn.execute(text(query), records)
    log.info(f"Saved centroid metadata to database for training_id={training_id} | records: {records}")

def load_artifact(engine: create_engine, artifact_name: str, query: str) -> object:
    with engine.begin() as conn:
        result = conn.execute(text(query), {"artifact_name": artifact_name})
        row = result.fetchone()
        if row is None:
            raise ValueError(f"No artifact found with name: {artifact_name}")
        obj = pickle.loads(row[0])
        log.info(f"Loaded artifact: {artifact_name} from database")
        return obj
    
def daily_assign_clusters(df: pd.DataFrame, scaler: RobustScaler, km: KMeans) -> tuple[pd.DataFrame, np.ndarray, dict]:
    # preprocess daily
    features = df[['recency', 'frequency', 'monetary']].copy()
    features['monetary'] = np.log1p(features['monetary'].astype(float))
    scaled = scaler.transform(features)

    # assign cluster labels
    label = km.predict(scaled)
    label_map = label_clusters(km, scaler)

    return df, label, label_map
