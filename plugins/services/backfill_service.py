import yaml
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from airflow.providers.postgres.hooks.postgres import PostgresHook
from services.checkpoint_service import *
from services.sql_service import *

CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"

def run_backfill(config_file_name):
    """
    Run backfill process based on configuration
    
    Args:
        config_file_name (str): Name of the YAML config file in contexts directory.
        Default: "test_write_pg.yaml"
    """
    try:
        # 1. Build config path dynamically
        config_path = str(Path(CONTEXTS_DIR) / config_file_name)
        log.info(f"Loading configuration from: {config_path}")
        
        # 2. Load configuration from YAML file
        with open(config_path) as f:
            config = yaml.safe_load(f)
            if not config:
                raise ValueError("Configuration file is empty or invalid")
            else:
                log.info("Configuration file loaded successfully")

        config_dict = {**config["postgres"], **config["postgres"]["target"]}
        log.info(f"Configuration parameters: {config_dict}")

        conn_id = schema = table = date = None
        for key, value in config_dict.items():
            # Skip nested dict
            if isinstance(value, dict):
                continue
            
            if value is None:
                raise ValueError(f"Configuration parameter '{key}' cannot be None")
 
            if 'con' in key.lower():
                conn_id = value
                log.info(f"Connection='{conn_id}'")
            elif 'schema' in key.lower():
                schema = value
                log.info(f"Schema='{schema}'")
            elif 'table' in key.lower():
                table = value
                log.info(f"Table='{table}'")
            elif 'date' in key.lower():
                date = value
                log.info(f"Date='{date}'")
        
        log.info(f"Done loading configuration parameters in: {config_path}")
        
        # Convert date object to datetime if needed
        if date and not isinstance(date, datetime):
            date = datetime.combine(date, datetime.min.time())
            log.info(f"Converted date to datetime: {date}")
        
        # Create Postgres hook
        log.info("Creating Postgres hook...")
        pg_hook = PostgresHook(postgres_conn_id=conn_id)
        if not pg_hook:
            raise ValueError(f"Failed to create pg_hook with conn_id '{conn_id}'")
        else:
            log.info("Postgres hook created successfully")

        # 2. Check existence of target table
        is_exist = check_exist_table(pg_hook, schema, table)

        if not is_exist:
            log.info(f"Table '{schema}.{table}' does not exist. It will be created.")

            raw_sql = (
                config['query']['function']['create'] + '\n' + config['query']['sql']
            )
            sql = render_template(
                raw_sql,
                schema=schema,
                table=table,
                start_date=date.strftime("%Y-%m-01"),
                end_date=(date + relativedelta(months=1)).strftime("%Y-%m-01")
            )
            log.info("Executing table creation SQL...")
            log.info(f"date parameter: {date}")
            log.info(f"Creating table with SQL: {sql}")
        else:
            log.info(f"Table '{schema}.{table}' exists.")

            raw_sql = (
                config['query']['function']['insert'] + '\n' + config['query']['sql']
            )
            date = get_max_date(pg_hook, schema, table)            
            # Convert date object to datetime if needed
            if date and not isinstance(date, datetime):
                date = datetime.combine(date, datetime.min.time())
                log.info(f"Converted max_date to datetime: {date}")
            if not date:
                raise ValueError(f"Failed to get max date from table '{schema}.{table}'")
            
            # Add 1 month to get next month for backfill
            date = date + relativedelta(months=1)
            log.info(f"start date for backfill: {date}")
        # 3. Render SQL query with parameters
        sql = render_template(
            raw_sql,
            schema=schema,
            table=table,
            start_date=date.strftime("%Y-%m-01"),
            end_date=(date + relativedelta(months=1)).strftime("%Y-%m-01")
        )  
        log.info(f"Rendered SQL: {sql}")

        # 4. Execute SQL query
        execute_sql(pg_hook, sql)
        
    except Exception as e:
        log.error(f"Error in backfill process: {str(e)}")
        raise