from airflow.providers.postgres.hooks.postgres import PostgresHook
import yaml
import logging
from dateutil.relativedelta import relativedelta
from services.kmeans_service import (
    daily_assign_clusters,
    extract_data,
    load_artifact,
    save_rfm_clusters,
)

# Logging configuration
log = logging.getLogger(__name__)

# Set contexts directory for config files (Default in Contexts folder, can be changed if needed)
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"

# Main orchestration function to run KMeans training process
def customer_segmentation_daily_assign(config_file_name, **context):
    try:
        # 1. Load configuration from YAML file
        log.info(f"1. Loading config from {config_file_name}...")
        with open(f"{CONTEXTS_DIR}/{config_file_name}", 'r') as file:
            config = yaml.safe_load(file)
        # connection
        conn = config['postgres']['conn_id']
        # daily data parameters
        daily_schema = config['postgres']['daily']['schema']
        daily_table = config['postgres']['daily']['table']
        daily_query = config['postgres']['daily']['query']
        # artifact parameters
        artifact_query = config['postgres']['artifact']['query']
        log.info(f"Config loaded. Daily Schema: {daily_schema}, Daily Table: {daily_table}, Connection ID: {conn}")

        # 2. Init PostgresHook and Engine
        log.info("2. Initializing PostgresHook and Engine...")
        pg_hook = PostgresHook(postgres_conn_id=conn)
        engine = pg_hook.get_sqlalchemy_engine()

        #3. Load execution date from Airflow context
        log.info("3. Loading execution date from Airflow context...")
        execution_date = context.get('execution_date')
        end_date = execution_date + relativedelta(days=1)
        if execution_date is None:
            raise ValueError("Execution date not found in Airflow context")
        log.info(f"Execution date: {execution_date}")

        # 4. Load artifacts
        log.info("4. Loading artifacts...")
        scaler = load_artifact(engine, "scaler", artifact_query)
        km = load_artifact(engine, "kmeans_model", artifact_query)
        if scaler is None or km is None:
            raise ValueError("Required artifacts not found in database")
        log.info("Artifacts loaded successfully")

        # 5. Extract daily data
        log.info("5. Extracting daily data...")
        df = extract_data(engine, daily_query, execution_date, end_date)

        # 6. Daily assign clusters (transform only, no training)
        log.info("6. Assigning clusters to daily data...")
        df, label, label_map = daily_assign_clusters(df, scaler, km)

        # 7. Save daily assigned clusters to database
        log.info("7. Saving daily assigned clusters to database...")
        save_rfm_clusters(daily_schema, daily_table, df, km, label_map, engine,
                          labels=label, if_exists='append', execution_date=execution_date.date())

    except Exception as e:
        log.error(f"Error during KMeans daily assign orchestration: {str(e)}")
        raise