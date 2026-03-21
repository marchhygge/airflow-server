from airflow.providers.postgres.hooks.postgres import PostgresHook
import yaml
import logging
from services.kmeans_service import (
    extract_data, 
    find_k,
    label_clusters, 
    preprocess,
    save_centroid_metadata,
    save_rfm_clusters,
    save_training_metadata, 
    train_KMeans,
    save_artifacts
)

# Logging configuration
log = logging.getLogger(__name__)

# Set contexts directory for config files (Default in Contexts folder, can be changed if needed)
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"

# Main orchestration function to run KMeans training process
def customer_segmentation_model_training(config_file_name):
    """
    Orchestrates the KMeans model training process for customer segmentation.
    Args:
    - config_file_name: str, the name of the config file in contexts directory
    Raises:
    - ValueError: If any validation fails or the training process encounters an error
    """
    try:
        # 1. Load config
        log.info(f"1. Loading config from {config_file_name}...")
        with open(f"{CONTEXTS_DIR}/{config_file_name}", 'r') as file:
            config = yaml.safe_load(file)
        
        # connection
        conn = config['postgres']['conn_id']

        # training data parameters
        training_schema = config['postgres']['training']['schema']
        training_table = config['postgres']['training']['table']
        start_date = config['postgres']['training']['start_date']
        end_date = config['postgres']['training']['end_date']
        training_query = config['postgres']['training']['query']

        # artifact parameters
        artifact_query = config['postgres']['artifact']['query']

        # metadata logging
        metadata_queries = config['postgres']['metadata']
        kmeans_training_log_query = metadata_queries['kmeans_training']['query']
        kmeans_centroid_log_query = metadata_queries['kmeans_centroid']['query']

        log.info(f"Config loaded. Schema: {training_schema}, table: {training_table}, Connection ID: {conn}, start_date: {start_date}, end_date: {end_date}")

        # 2. Init PostgresHook and Engine
        log.info("2. Initializing PostgresHook and Engine...")
        pg_hook = PostgresHook(postgres_conn_id=conn)
        engine = pg_hook.get_sqlalchemy_engine()

        # 3. Extract data
        log.info("3. Extracting data...")
        df = extract_data(engine, training_query, start_date, end_date)
        log.info("\n" + "Sample data:" + "\n" + df.head(10).to_markdown(index=False))

        # 4. Preprocess data
        log.info("4. Preprocessing data...")
        scaled_data, scaler = preprocess(df)

        # 5. Find optimal k (optional, can be commented out if not needed)
        log.info("5. Finding optimal k...")
        find_k(scaled_data)

        # 6. Train KMeans model
        log.info(f"6. Training KMeans model ...")
        km = train_KMeans(scaled_data)

        # 7. Label clusters
        log.info("7. Labeling clusters...")
        cluster_labels = label_clusters(km, scaler)

        # 8. save artifacts to database
        log.info("8. Saving artifacts to database...")
        save_artifacts(engine, "kmeans_model", km, artifact_query)
        save_artifacts(engine, "scaler", scaler, artifact_query)

        # 9. save training rfm data to database
        log.info("9. Saving cluster labels to database...")
        n_samples = save_rfm_clusters(training_schema, training_table, df, km, cluster_labels, engine)

        # 10. save training metadata to database
        log.info("10. Saving training metadata to database...")
        training_id = save_training_metadata(engine, km, scaler, scaled_data, kmeans_training_log_query, start_date, end_date, n_samples)

        # 11. save centroid metadata to database
        log.info("11. Saving centroid metadata to database...")
        save_centroid_metadata(engine, km, scaler, kmeans_centroid_log_query, training_id, cluster_labels)

    except Exception as e:
        log.error(f"Error during KMeans model training orchestration: {str(e)}")
        raise