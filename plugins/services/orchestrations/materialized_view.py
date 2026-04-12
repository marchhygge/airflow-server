"""
Service for refreshing PostgreSQL materialized views.

Config file (YAML) structure:
  postgres:
    conn_id: <airflow_conn_id>
  views:
    - schema: <schema_name>
      concurrently: true | false   # default: false
      names:
        - <view_name>
        - <view_name>
"""

from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging

from services.core.config import load_config
from services.core.sql import execute_sql
from services.core.validate import validate_identifier, validate_pg

log = logging.getLogger(__name__)


def refresh_materialized_views(config_file_name: str, **context):
    """
    Refresh all materialized views listed in the given config file.

    Args:
        config_file_name : YAML config file path relative to contexts/ directory
        **context        : Airflow context (unused, kept for PythonOperator compatibility)
    """
    try:
        # 1. Load config
        log.info(f"1. Loading config from {config_file_name}...")
        config = load_config(config_file_name)

        # 2. Validate top-level keys
        if "postgres" not in config or "conn_id" not in config["postgres"]:
            raise ValueError("Config missing required key: 'postgres.conn_id'")
        if "views" not in config or not isinstance(config["views"], list):
            raise ValueError("Config missing required key: 'views' (must be a list)")
        
        conn_id = config["postgres"]["conn_id"]
        validate_identifier(conn_id, "conn_id")

        # 3. Connect
        log.info(f"2. Connecting to PostgreSQL via conn_id='{conn_id}'...")
        pg_hook = PostgresHook(postgres_conn_id=conn_id)
        validate_pg(pg_hook)

        # 4. Flatten groups and refresh each view
        log.info("3. Starting materialized view refresh...")
        total = 0
        for group in config["views"]:
            if "schema" not in group:
                raise ValueError("Each views entry must have a 'schema' key")
            if "names" not in group or not isinstance(group["names"], list):
                raise ValueError(f"views entry for schema '{group['schema']}' must have a 'names' list")

            schema       = group["schema"]
            concurrently = group.get("concurrently", False)
            keyword      = "CONCURRENTLY " if concurrently else ""

            validate_identifier(schema, "schema")

            for name in group["names"]:
                validate_identifier(name, "view name")
                sql = f"REFRESH MATERIALIZED VIEW {keyword}{schema}.{name};"
                log.info(f"Refreshing: {schema}.{name} (concurrently={concurrently})...")
                execute_sql(pg_hook, sql)
                log.info(f"Done: {schema}.{name}")
                total += 1

        log.info(f"All {total} materialized view(s) refreshed successfully.")

    except Exception as e:
        log.error(f"refresh_materialized_views failed: {str(e)}")
        raise
