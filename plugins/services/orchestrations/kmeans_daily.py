from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging
from datetime import date, timedelta
from services.core.config import load_config
from services.ml.kmeans import (
    compute_rfm,
    daily_assign_clusters,
    extract_data,
    load_artifact,
    save_rfm_clusters,
)

log = logging.getLogger(__name__)

# Days of order history to pull for recency calculation.
# Must cover the full training period so recency distribution matches training.
RECENCY_LOOKBACK_DAYS = 180


def customer_segmentation_daily_assign(config_file_name, **context):
    """
    Daily pipeline: assign each active customer to a cluster using the trained model.

    Steps:
      1. Load config
      2. Init DB connection
      3. Resolve execution date and date window
      4. Load artifacts (scaler + KMeans)
      5. Extract raw order data (180-day lookback for recency)
      6. Compute RFM features (recency full-lookback, freq/monetary 30-day window)
      7. Assign clusters (transform-only, no retraining)
      8. Save daily cluster assignments
    """
    try:
        # 1. Load config
        log.info(f"1. Loading config: {config_file_name}")
        config = load_config(config_file_name)

        conn           = config['postgres']['conn_id']
        daily_schema   = config['postgres']['daily']['schema']
        daily_table    = config['postgres']['daily']['table']
        daily_query    = config['postgres']['daily']['query']
        window_days    = config['postgres']['daily']['window_days']
        artifact_query = config['postgres']['artifact']['query']
        dataset_start  = date.fromisoformat(config['postgres']['replay']['dataset_start'])
        real_start     = date.fromisoformat(config['postgres']['replay']['real_start'])

        log.info(f"Config loaded | schema={daily_schema} | table={daily_table} | window={window_days}d")

        # 2. Init DB connection
        log.info("2. Initializing DB connection...")
        pg_hook = PostgresHook(postgres_conn_id=conn)
        engine  = pg_hook.get_sqlalchemy_engine()

        # 3. Resolve execution date → map sang dataset date
        log.info("3. Resolving execution date...")
        execution_date = context.get('execution_date')
        if execution_date is None:
            raise ValueError("execution_date not found in Airflow context")

        # map real execution_date → dataset snapshot_date
        days_offset   = (execution_date.date() - real_start).days
        snapshot_date = dataset_start + timedelta(days=days_offset)
        start_date    = snapshot_date - timedelta(days=RECENCY_LOOKBACK_DAYS)
        end_date      = snapshot_date

        log.info(
            f"dataset_start={dataset_start} | real_start={real_start} | "
            f"real_date={execution_date.date()} | offset={days_offset}d | "
            f"snapshot={snapshot_date} | extract window={start_date} -> {end_date} | "
            f"RFM window={window_days}d"
        )

        # 4. Load artifacts
        log.info("4. Loading artifacts...")
        scaler = load_artifact(engine, "scaler", artifact_query)
        km     = load_artifact(engine, "kmeans_model", artifact_query)
        log.info("Artifacts loaded")

        # 5. Extract raw order data
        log.info("5. Extracting raw order data...")
        df = extract_data(engine, daily_query, start_date, end_date)

        # 6. Compute RFM features
        log.info(f"6. Computing RFM (snapshot={snapshot_date}, window={window_days}d)...")
        rfm = compute_rfm(df, snapshot_date, window_days)

        # 7. Assign clusters
        log.info("7. Assigning clusters...")
        rfm, labels, label_map = daily_assign_clusters(rfm, scaler, km)

        # 8. Save results
        log.info("8. Saving daily cluster assignments...")
        save_rfm_clusters(
            daily_schema, daily_table, rfm, km, label_map, engine,
            labels=labels, if_exists='append', execution_date=snapshot_date
        )

    except Exception as e:
        log.error(f"Daily assign failed: {e}")
        raise
