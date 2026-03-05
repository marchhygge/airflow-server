"""
This module provides utility functions for interacting with APIs, 
including 
validating API responses, 
loading configuration from YAML files, 
retrieving API keys from Airflow Variables, and 
loading data into PostgreSQL using SQLAlchemy. 
It is designed to be used in the context of Airflow DAGs for orchestrating tasks that involve API calls and database interactions.
"""

import requests
from pathlib import Path
import yaml
import pandas as pd
from airflow.models import Variable
from airflow.providers.postgres.hooks.postgres import PostgresHook
from sqlalchemy import inspect

# Set contexts directory for config files (Default in Contexts folder, can be changed if needed)
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"

# Define a dictionary of error messages corresponding to different error types that the API might return.
def validate_api_status(response, messages):
    # First, attempt to parse the JSON response. If parsing fails, raise an error with the raw response text.
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        raise ValueError(f"HTTP {response.status_code} | Invalid JSON response: {response.text}")
    
    result_status = data.get("result")
    
    # Handle API-specific error responses based on the "result" field in the JSON data.
    if not response.ok and result_status == "error":
        error_type = data.get("error-type", "unknown")
        solution = messages.get(error_type, "unknown error")
        raise ValueError(f"HTTP {response.status_code} | Error type: {error_type} | Solution: {solution}")

    # If the response is successful and the API indicates success, return the data.
    elif response.ok and result_status == "success":
        return data

    # If the response structure is unexpected, raise an error.
    else:
        raise ValueError(f"Unexpected API response structure: result='{result_status}'")

# Load configuration from YAML
def load_config(config_file_name: str):
    config_path = Path(CONTEXTS_DIR) / config_file_name
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)

# Retrieve the API key from Airflow Variables.
def get_api_key():
    api_key = Variable.get("exchange_rate_api_key", default_var=None)
    if not api_key:
        raise ValueError("API key 'exchange_rate_api_key' not found in Airflow Variables.")
    return api_key

def load_df_to_postgres(dataframe: pd.DataFrame, conn_id: str, schema: str, table_name: str):
    # 1. Init PostgresHook
    pg_hook = PostgresHook(postgres_conn_id=conn_id)
    if pg_hook is None:
        raise ValueError(f"Failed to initialize PostgresHook with connection ID '{conn_id}'")

    # 2. Get SQLAlchemy engine from PostgresHook
    engine = pg_hook.get_sqlalchemy_engine()
    if engine is None:
        raise ValueError(f"Failed to get SQLAlchemy engine from PostgresHook with connection ID '{conn_id}'")

    # 3. Truncate table if exists (to avoid breaking dependent views/materialized views)
    with engine.connect() as conn:
        try:
            conn.execute(f"TRUNCATE TABLE {schema}.{table_name}")
            conn.commit()
        except Exception:
            # Table doesn't exist yet, will be created below
            pass

    # 4. Load DataFrame to PostgreSQL
    dataframe.to_sql(
        name=table_name,
        con=engine,
        schema=schema,
        if_exists="append", # Append data to existing table structure
        index=False, # Do not write DataFrame index as a column in the database
        method="multi", # Use multi-row insert for better performance
        chunksize=1000 # Insert 1000 rows at a time
    )

    # 5. refresh materialized views that depend on this table (if any)
    inspector = inspect(engine)
    with engine.connect() as conn:
        dependent_views = inspector.get_view_names(schema=schema)
        for view in dependent_views:
            conn.execute(f"REFRESH MATERIALIZED VIEW {schema}.{view}")
        conn.commit()
