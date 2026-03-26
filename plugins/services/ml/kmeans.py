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
    Returns raw order rows: customer_unique_id, event_date, revenue
    (one row per order — GROUP BY customer + date + order_id in SQL).
    args:
     - engine: SQLAlchemy engine
     - query: SQL with {start_date} and {end_date} placeholders
     - start_date: training start date
     - end_date: training end date (= snapshot_date)
    returns:
     - pd.DataFrame with columns: customer_unique_id, event_date, revenue
    """
    try:
        query_resolved = query.format(start_date=start_date, end_date=end_date)
        log.info(f"Executing query:\n{query_resolved}")
        with engine.connect() as conn:
            result = conn.execute(text(query_resolved))
            df = pd.DataFrame(result)
            log.info(f"Extracted {len(df):,} rows | {df['customer_unique_id'].nunique():,} unique customers")
            return df
    except Exception as e:
        log.error(f"Error executing query: {e}")
        raise


def compute_rfm(df: pd.DataFrame, snapshot_date: str, window_days: int) -> pd.DataFrame:
    """
    Computes RFM features from raw order data. Returns one row per customer.

    Feature definitions:
     - Recency    : days since last purchase relative to snapshot_date (full period)
     - freq_30d   : number of orders within the last window_days
     - monetary_30d: total revenue within the last window_days

    Customers who bought outside the window get freq_30d=0, monetary_30d=0
    (they become Cooling Down or Dormant segments).

    args:
     - df: raw order DataFrame with columns: customer_unique_id, event_date, revenue
     - snapshot_date: reference date for recency calculation (typically end_date)
     - window_days: lookback window in days for frequency and monetary
    returns:
     - pd.DataFrame: one row per customer with recency, freq_30d, monetary_30d, snapshot_date
    """
    snapshot_date = pd.to_datetime(snapshot_date)
    window_start = snapshot_date - pd.Timedelta(days=window_days)
    df = df.copy()
    df['event_date'] = pd.to_datetime(df['event_date'])

    all_users = df[['customer_unique_id']].drop_duplicates()

    # Recency: days from last order (full period) to snapshot_date
    recency_df = (
        df.groupby('customer_unique_id')['event_date']
        .max()
        .reset_index()
        .rename(columns={'event_date': 'last_order_date'})
    )
    recency_df['recency'] = (snapshot_date - recency_df['last_order_date']).dt.days

    # Frequency & Monetary: within window only
    df_window = df[df['event_date'] >= window_start].copy()
    rfm_window = (
        df_window.groupby('customer_unique_id')
        .agg(
            freq_30d=('event_date', 'count'),
            monetary_30d=('revenue', 'sum')
        )
    )

    # Assemble: 1 row per customer
    rfm = (
        all_users
        .merge(recency_df[['customer_unique_id', 'recency']], on='customer_unique_id', how='left')
        .merge(rfm_window, on='customer_unique_id', how='left')
    )
    # Customers with no orders in the window get freq_30d=0, monetary_30d=0
    rfm['freq_30d'] = rfm['freq_30d'].fillna(0).astype(int)
    rfm['monetary_30d'] = rfm['monetary_30d'].fillna(0.0)
    rfm['snapshot_date'] = snapshot_date.date()

    n_zero_freq = (rfm['freq_30d'] == 0).sum()
    log.info(
        f"RFM computed: {len(rfm):,} customers | snapshot={snapshot_date.date()} | window={window_days}d\n"
        f"  freq=0 (outside window): {n_zero_freq:,} ({n_zero_freq / len(rfm):.1%})"
    )
    return rfm


def preprocess(df: pd.DataFrame) -> tuple[np.ndarray, RobustScaler]:
    """
    Preprocesses RFM DataFrame for KMeans clustering.
    Applies log1p to both freq_30d and monetary_30d, then RobustScaler.

    args:
     - df: DataFrame with columns: recency, freq_30d, monetary_30d
    returns:
     - tuple[np.ndarray, RobustScaler]: scaled feature matrix and fitted scaler
    """
    try:
        features = df[['recency', 'freq_30d', 'monetary_30d']].copy()
        features['freq_30d'] = np.log1p(features['freq_30d'])
        features['monetary_30d'] = np.log1p(features['monetary_30d'].astype(float))

        scaler = RobustScaler()
        scaled = scaler.fit_transform(features)
        log.info(
            f"Scaler fitted | center={scaler.center_.round(4)} | scale={scaler.scale_.round(4)}\n"
            + pd.DataFrame(scaled, columns=['recency', 'log_freq_30d', 'log_monetary_30d']).describe().round(3).to_string()
        )
        return scaled, scaler
    except KeyError as e: # Missing expected column
        raise ValueError(f"Missing required column: {e}")
    except Exception as e: # Catch-all for other preprocessing errors
        raise Exception(f"Error during preprocessing: {e}")


def find_k(scaled_data: np.ndarray, k_range=range(2, 8)):
    """
    Evaluates KMeans for each k using inertia and silhouette score.
    """
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        lbl = km.fit_predict(scaled_data)
        sil = silhouette_score(scaled_data, lbl)
        log.info(f"k={k} | inertia={km.inertia_:,.1f} | silhouette={sil:.4f}")


def train_KMeans(scaled_data: np.ndarray, n_clusters: int = 3) -> KMeans:
    """
    Trains a KMeans model on scaled RFM data.
    args:
     - scaled_data: output of preprocess()
     - n_clusters: number of segments (default 3)
    returns:
     - KMeans: fitted model
    """
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10, max_iter=300)
    km.fit(scaled_data)
    sil = silhouette_score(scaled_data, km.labels_)
    log.info(f"KMeans trained | n_clusters={n_clusters} | inertia={km.inertia_:,.1f} | silhouette={sil:.4f}")
    return km


def label_clusters(km: KMeans, scaler: RobustScaler) -> dict:
    """
    Maps numeric cluster IDs to business segment names based on centroid recency rank.

    Segment logic (recency rank ascending = lower days = more recent = better):
     - rank 1 (lowest recency) → active_buyers
     - rank 2                  → cooling_down
     - rank 3 (highest)        → dormant
    """
    centroids_orig = scaler.inverse_transform(km.cluster_centers_)

    centroid_df = pd.DataFrame({
        'cluster':      range(len(centroids_orig)),
        'recency':      centroids_orig[:, 0],
        'freq_30d':     np.expm1(centroids_orig[:, 1]),
        'monetary_30d': np.expm1(centroids_orig[:, 2]),
    })

    centroid_df['r_rank'] = centroid_df['recency'].rank(ascending=True)

    segment_map = {1: 'active_buyers', 2: 'cooling_down', 3: 'dormant'}
    label_map = {
        int(row['cluster']): segment_map[int(row['r_rank'])]
        for _, row in centroid_df.iterrows()
    }

    log.info(
        "\n=== Cluster centroids (original scale) ===\n"
        + centroid_df[['cluster', 'recency', 'freq_30d', 'monetary_30d', 'r_rank']].to_string(index=False)
        + f"\nLabel map: {label_map}"
    )
    return label_map


def save_artifacts(engine: create_engine, artifacts_name: str, obj, artifact_query: str) -> None:
    data = pickle.dumps(obj)
    with engine.begin() as conn:
        conn.execute(text(artifact_query), {
            "artifact_name": artifacts_name,
            "artifact_data": data,
            "updated_at": pd.Timestamp.now()
        })
    log.info(f"Saved artifact: {artifacts_name}")


def save_rfm_clusters(schema: str, table_name: str, df: pd.DataFrame, km: KMeans, label_map: dict, engine: create_engine,
                    labels: np.ndarray = None, if_exists: str = 'replace', execution_date=None) -> int:
    """
    Saves RFM cluster assignments to the database.
    Renames freq_30d → frequency and monetary_30d → monetary for storage.
    """
    result = df[['customer_unique_id', 'recency', 'freq_30d', 'monetary_30d']].copy()
    result = result.rename(columns={'freq_30d': 'frequency', 'monetary_30d': 'monetary'})
    result['cluster_id'] = labels if labels is not None else km.labels_
    result['cluster_name'] = result['cluster_id'].map(label_map)
    result['updated_at'] = pd.Timestamp.now()

    if execution_date is not None:
        result['execution_date'] = execution_date
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {schema}.{table_name} WHERE execution_date = :execution_date"),
                {"execution_date": execution_date}
            )
        log.info(f"Deleted existing records for execution_date={execution_date}")

    log.info("\nCluster sample:\n" + result.head(10).to_markdown(index=False))
    result.to_sql(table_name, engine, schema=schema, if_exists=if_exists, index=False)
    log.info(f"Saved {len(result):,} records to {schema}.{table_name}")
    return len(result)


def save_training_metadata(engine: create_engine, km: KMeans, scaler: RobustScaler, scaled_data: np.ndarray,
                            query: str, start_date: str, end_date: str, n_samples: int):
    """
    Saves training run metadata and scaler parameters to the database.
    Scaler stores log-transformed medians/IQRs for features: [recency, log_freq_30d, log_monetary_30d].
    """
    sil = silhouette_score(scaled_data, km.labels_)
    with engine.begin() as conn:
        result = conn.execute(text(query), {
            "trained_at":        pd.Timestamp.now(),
            "start_date":        start_date,
            "end_date":          end_date,
            "n_samples":         n_samples,
            "n_clusters":        km.n_clusters,
            "inertia":           km.inertia_,
            "silhouette":        float(sil),
            "n_iter":            km.n_iter_,
            "recency_median":    float(scaler.center_[0]),
            "frequency_median":  float(scaler.center_[1]),
            "monetary_median":   float(scaler.center_[2]),
            "recency_iqr":       float(scaler.scale_[0]),
            "frequency_iqr":     float(scaler.scale_[1]),
            "monetary_iqr":      float(scaler.scale_[2]),
        })
        training_id = result.fetchone()[0]

    log.info(
        f"Training metadata saved | training_id={training_id} | silhouette={sil:.4f} | "
        f"inertia={km.inertia_:,.1f}"
    )
    return training_id


def save_centroid_metadata(engine: create_engine, km: KMeans, scaler: RobustScaler,
                            query: str, training_id: int, label_map: dict) -> None:
    """
    Saves centroid coordinates (scaled and original scale) to the database.
    Both frequency_orig and monetary_orig are inverse-log-transformed via expm1.
    """
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
            "frequency_orig":   float(np.expm1(centroids_orig[cluster_id][1])),
            "monetary_orig":    float(np.expm1(centroids_orig[cluster_id][2])),
        })
    with engine.begin() as conn:
        conn.execute(text(query), records)
    log.info(f"Centroid metadata saved for training_id={training_id} | {records}")


def load_artifact(engine: create_engine, artifact_name: str, query: str) -> object:
    with engine.begin() as conn:
        result = conn.execute(text(query), {"artifact_name": artifact_name})
        row = result.fetchone() # Expecting one row with artifact_data column
        if row is None:
            raise ValueError(f"No artifact found: {artifact_name}")
        obj = pickle.loads(row[0])
        log.info(f"Loaded artifact: {artifact_name}")
        return obj


def daily_assign_clusters(df: pd.DataFrame, scaler: RobustScaler, km: KMeans) -> tuple[pd.DataFrame, np.ndarray, dict]:
    """
    Assigns cluster labels to daily RFM data using the trained scaler and model.
    Applies the same log1p transform as training: both freq_30d and monetary_30d.

    args:
     - df: DataFrame with columns: recency, freq_30d, monetary_30d
     - scaler: fitted RobustScaler from training
     - km: fitted KMeans from training
    returns:
     - (df, labels, label_map)
    """
    features = df[['recency', 'freq_30d', 'monetary_30d']].copy()
    features['freq_30d'] = np.log1p(features['freq_30d'])
    features['monetary_30d'] = np.log1p(features['monetary_30d'].astype(float))

    scaled = scaler.transform(features)
    labels = km.predict(scaled)
    label_map = label_clusters(km, scaler)

    log.info(f"Daily assign: {len(df):,} customers assigned")
    return df, labels, label_map
