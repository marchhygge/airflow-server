import logging
from airflow.providers.postgres.hooks.postgres import PostgresHook
from services.dag_services import get_execution_date
from services.backfill_services import build_sql_for_day, resolve_raw_sql
from services.sql_services import check_exist_table, render_template
from services.api_services import load_config
from services.validate_services import (
    validate_config,
    validate_convert_datetime,
    validate_identifier,
    validate_logic_date,
    validate_pg, 
    validate_sql
)

log = logging.getLogger(__name__)

# Set contexts directory for config files (Default in Contexts folder, can be changed if needed)
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"

def run_operation(config_file_name, **context):

    try:
        execution_date = get_execution_date(**context)
        execution_date = validate_convert_datetime(execution_date)

        # 1. Load config
        log.info(f"1. Loading config from {config_file_name}...")

        config = load_config(config_file_name)
        validate_config(config)

        raw_sql = config['query']['sql']
        validate_sql(raw_sql)

        # Flatten configuration
        config_dict = {**config["postgres"], **config["postgres"]["target"]}

        conn_id = schema = table = start_date = end_date = based_on = date_column = None
        for k,v in config_dict.items():
            if isinstance(v, dict):
                continue
            if "con" in k.lower():
                conn_id = v
                validate_identifier(conn_id, "conn_id")
            elif "schema" in k.lower():
                schema = v
                validate_identifier(schema, "schema")
            elif "table" in k.lower():
                table = v
                validate_identifier(table, "table")
            elif "start_date" in k.lower():
                start_date = v
                start_date = validate_convert_datetime(start_date)
            elif "end_date" in k.lower():
                end_date = v
                if not end_date.lower() == "none":
                    end_date = validate_convert_datetime(end_date)
                    # If end_date is provided, validate logic between start_date and end_date
                    validate_logic_date(start_date, end_date) 
            elif "based_on" in k.lower():
                based_on = v
                if based_on:
                    validate_identifier(based_on, "based_on_table")
            elif "date_column" in k.lower():
                date_column = v
                if based_on and not date_column:
                    raise ValueError("date_column is required in config when based_on is provided. EX: date_column: order_date")
                if date_column:
                    validate_identifier(date_column, "date_column")
        log.info(f"Config parameters extracted: conn_id={conn_id}, schema={schema}, table={table}, start_date={start_date}, end_date={end_date}, based_on={based_on}, date_column={date_column}")

        # 2. Init Postgres hook
        log.info(f"2. Initializing PostgresHook with connection ID '{conn_id}'...")
        pg_hook = PostgresHook(postgres_conn_id=conn_id)
        validate_pg(pg_hook)

        # 3. Check if table exists
        log.info(f"3. Checking if target table '{schema}.{table}' exists...")

        is_exist = check_exist_table(pg_hook, schema, table)
        process_sql = resolve_raw_sql(config, is_exist)
        process_date = None
        if not is_exist:
            process_date = start_date
        else:
            process_date = execution_date
            if end_date and process_date > end_date:
                log.info(f"Execution date {process_date} is greater than end_date {end_date}. No operation will be performed.")
                return
        
        #4. Render SQL
        log.info("4. Building SQL for execution...")
        sql = build_sql_for_day(
            process_sql,
            schema,
            table,
            process_date,
            render_template
        )
        
        # 5. Execute SQL
        log.info(f"5. Executing SQL: {sql}")
        pg_hook.run(sql)
    except Exception as e :
        log.error(f"Error during operation orchestration: {e}")
        raise