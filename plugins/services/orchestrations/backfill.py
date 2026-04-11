import yaml
from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from services.core.sql import (
    check_exist_table,
    check_data_available,
    render_template,
    execute_sql,
    get_max_date
)
from services.core.backfill_services import (
    resolve_raw_sql,
    resolve_start_date_dt,
    build_sql_for_month
)
from services.core.validate import (
    validate_config,
    validate_identifier,
    validate_logic_date,
    validate_convert_datetime,
    validate_pg,
    validate_sql
)
from services.core.config import load_config

# logging configuration
log = logging.getLogger(__name__)

# Set contexts directory for config files (Default in Contexts folder, can be changed if needed)

# Main orchestration function to run backfill process
def run_backfill(config_file_name, real_start: date, dataset_start: date, **context):
    """
    Docstring for run_backfill as orchestration function to run backfill process
    Args:
    - config_file_name: str, the name of the config file in contexts directory
    - real_start: date, the first real execution date of the DAG
    - dataset_start: date, the first date of the dataset to replay
    - **context: Airflow context (contains execution_date, etc.)
    Raises:
    - ValueError: If any validation fails or backfill process encounters an error
    """
    try:
        # 1. Load config
        log.info(f"1. Loading config from {config_file_name}...")
        config = load_config(config_file_name)

        # validate config structure and content before processing
        validate_config(config)

        # Extract parameters by keywords
        raw_sql_template = config['query']['sql']
        validate_sql(raw_sql_template)

        # Flatten configuration
        config_dict = {**config["postgres"], **config["postgres"]["target"]}

        conn_id = schema = table = start_date = end_date = based_on = None
        for k, v in config_dict.items():
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
                end_date = validate_convert_datetime(end_date)
            elif "based_on" in k.lower():
                based_on = v
                if based_on:
                    validate_identifier(based_on, "based_on_table")
            elif "date_column" in k.lower():
                date_column = v
                validate_identifier(date_column, "date_column")
        # Override end_date bằng snapshot_date tính từ replay offset
        execution_date = context['execution_date'].date()
        offset         = (execution_date - real_start).days
        snapshot_date  = dataset_start + timedelta(days=offset)
        end_date       = validate_convert_datetime(snapshot_date + timedelta(days=1))  # exclusive upper bound
        log.info(f"Config loaded: conn_id={conn_id}, schema={schema}, table={table}, start_date={start_date}, date_column={date_column}")
        log.info(f"Replay config: real_start={real_start} | dataset_start={dataset_start}")
        log.info(f"Replay offset: real={execution_date} | offset={offset}d | snapshot={snapshot_date} | sql_end_date={snapshot_date + timedelta(days=1)} (exclusive)")

        # 2. Validate inputs
        log.info("2. Validating input parameters...")

        # Validate logic date
        validate_logic_date(start_date, end_date)

        # 3. Init Postgres hook
        log.info("3. Initializing PostgreSQL connection...")
        pg_hook = PostgresHook(postgres_conn_id=conn_id)

        # Validate pg_hook
        validate_pg(pg_hook)

        # 4. Check table & get max_date to compare with end_date (if table exists)
        log.info("4. Checking table existance and getting max date")
        is_exist = check_exist_table(pg_hook, schema, table)
        max_date = None
        if is_exist:
            max_date = get_max_date(pg_hook, schema, table, based_on, date_column)
            if max_date:
                max_date = validate_convert_datetime(max_date) 
                if max_date >= end_date:
                    log.info(f"Table {schema}.{table} is already up to date with max_date={max_date:%Y-%m-%d}, skipping backfill")
                    return

        # 5. Resolve SQL & start date
        log.info("5. Resolving SQL template and start date for backfill...")
        process_sql = resolve_raw_sql(config, is_exist)
        start_date_dt = resolve_start_date_dt(table, max_date, start_date, is_exist)

        # 6. Backfill loop (Check data availability and execute SQL month by month)
        log.info("6. Starting backfill")
        max_run = 24
        current_run = 0
        execute = False
        while start_date_dt <= end_date and current_run < max_run: 

            # Check data availability if table exists
            raw_sql = build_sql_for_month(raw_sql_template, schema, table, start_date_dt, render_template) 
            if is_exist and not check_data_available(pg_hook, raw_sql):
                log.info(f"No data for {start_date_dt:%Y-%m}, skipping")
                start_date_dt += relativedelta(months=1)
                current_run += 1
                continue
            
            # Execute SQL
            sql = build_sql_for_month(process_sql, schema, table, start_date_dt, render_template)
            execute_sql(pg_hook, sql)
            execute = True
            break
        
        # If loop ends without execution, it means there is no data available for 24 months 
        if not execute:
            log.info(f"No executable month found in range {start_date:%Y-%m} to {end_date:%Y-%m}. Skipping.")
            return

    except Exception as e:
        log.error(f"Backfill failed: {str(e)}")
        raise