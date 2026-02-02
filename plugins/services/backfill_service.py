import yaml
from airflow.providers.postgres.hooks.postgres import PostgresHook
from services.checkpoint_service import *
from services.sql_service import *

CONFIG_PATH = "/home/ubuntu/airflow/airflow-server/contexts/test_write_pg.yaml"

def run_backfill():
    """
    Run backfill process based on configuration
    """
    # load config
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    conn_id = config["postgres"]["conn_id"]
    schema  = config["postgres"]["target"]["schema"]
    table   = config["postgres"]["target"]["table"]
    job_name = config["postgres"]["target"]["table"]

    pg_hook = PostgresHook(postgres_conn_id=conn_id, schema=schema)

    # checkpoint
    last_processed_month = get_last_processed_month(pg_hook, job_name)
    month_start, month_end = get_next_month(last_processed_month)

    # check table exists
    exist = check_exist_table(pg_hook, table)

    raw_sql = (
        config['query']['insert_sql'] 
        if exist 
        else config['query']['create_sql']
    )

    # render sql 
    sql = render_template(
        raw_sql,
        schema=schema,
        table=table,
        month_start=month_start.strftime("%Y-%m-01"),
        month_end=month_end.strftime("%Y-%m-01")
    )

    # execute sql
    execute_sql(pg_hook, sql)

    # update checkpoint
    update_last_processed_month(pg_hook, job_name, month_start) 