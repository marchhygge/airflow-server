from airflow.providers.postgres.hooks.postgres import PostgresHook
import yaml
import logging
from services.ml.kmeans import (
from services.credentials.config import CONTEXTS_DIR, load_config
    compute_rfm,
    extract_data,
    find_k,
    label_clusters,
    preprocess,
    save_artifacts,
    save_centroid_metadata,
    save_rfm_clusters,
    save_training_metadata,
    train_KMeans,
)

log = logging.getLogger(__name__)



def customer_segmentation_model_training(config_file_name):
    """
    Orchestrates the KMeans RFM model training pipeline.

    Steps:
      1.  Load config
      2.  Init DB connection
      3.  Extract raw order data
      4.  Compute RFM features (recency full-period, freq/monetary 30-day window)
      5.  Preprocess (log1p + RobustScaler)
      6.  Find optimal k (informational)
      7.  Train KMeans
      8.  Label clusters (active_buyers / cooling_down / dormant)
      9.  Save model artifacts (scaler + kmeans)
      10. Save RFM cluster assignments
      11. Save training metadata
      12. Save centroid metadata
    """
    try:
        # 1. Load config
        log.info(f"1. Loading config: {config_file_name}")
        config = load_config(config_file_name)

        conn             = config['postgres']['conn_id']
        training_schema  = config['postgres']['training']['schema']
        training_table   = config['postgres']['training']['table']
        start_date       = config['postgres']['training']['start_date']
        end_date         = config['postgres']['training']['end_date']
        snapshot_date    = config['postgres']['training']['snapshot_date']
        window_days      = config['postgres']['training']['window_days']
        n_clusters       = config['postgres']['training']['n_clusters']
        training_query   = config['postgres']['training']['query']
        artifact_query   = config['postgres']['artifact']['query']
        kmeans_training_log_query = config['postgres']['metadata']['kmeans_training']['query']
        kmeans_centroid_log_query = config['postgres']['metadata']['kmeans_centroid']['query']

        log.info(
            f"Config loaded | schema={training_schema} | table={training_table} | "
            f"period={start_date} -> {end_date} | snapshot={snapshot_date} | "
            f"window={window_days}d | n_clusters={n_clusters}"
        )

        # 2. Init DB connection
        log.info("2. Initializing DB connection...")
        pg_hook = PostgresHook(postgres_conn_id=conn)
        engine  = pg_hook.get_sqlalchemy_engine()

        # 3. Extract raw order data
        log.info("3. Extracting raw order data...")
        df = extract_data(engine, training_query, start_date, end_date)

        # 4. Compute RFM features
        log.info(f"4. Computing RFM features (snapshot={snapshot_date}, window={window_days}d)...")
        rfm = compute_rfm(df, snapshot_date, window_days)

        # 5. Preprocess (log1p + RobustScaler)
        log.info("5. Preprocessing features...")
        scaled_data, scaler = preprocess(rfm)

        # 6. Find optimal k (informational)
        log.info("6. Finding optimal k...")
        find_k(scaled_data)

        # 7. Train KMeans
        log.info(f"7. Training KMeans (n_clusters={n_clusters})...")
        km = train_KMeans(scaled_data, n_clusters)

        # 8. Label clusters
        log.info("8. Labeling clusters...")
        label_map = label_clusters(km, scaler)

        # 9. Save artifacts
        log.info("9. Saving artifacts...")
        save_artifacts(engine, "kmeans_model", km, artifact_query)
        save_artifacts(engine, "scaler", scaler, artifact_query)

        # 10. Save RFM cluster assignments
        log.info("10. Saving RFM cluster assignments...")
        n_samples = save_rfm_clusters(
            training_schema, training_table, rfm, km, label_map, engine
        )

        # 11. Save training metadata
        log.info("11. Saving training metadata...")
        training_id = save_training_metadata(
            engine, km, scaler, scaled_data,
            kmeans_training_log_query, start_date, end_date, n_samples
        )

        # 12. Save centroid metadata
        log.info("12. Saving centroid metadata...")
        save_centroid_metadata(engine, km, scaler, kmeans_centroid_log_query, training_id, label_map)

    except Exception as e:
        log.error(f"KMeans training failed: {e}")
        raise
