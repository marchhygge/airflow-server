"""
Core operator for star schema pipelines (fact + dim tables).

Date mapping:
  A = real_start          : date when the DAG first runs in production
  B = dataset_start       : first date of the source dataset
  C = execution_date      : from Airflow context

  offset                  = C - A  (days)
  dataset_execution_date  = B + offset

SQL window:
  month_start = first day of month(dataset_execution_date)
  daily_end   = dataset_execution_date + 1 day  (exclusive upper bound)

Logic (per run):
  - Table not exist → CREATE TABLE AS SELECT ... WHERE [month_start, daily_end)
  - Table exists    → EXCEPT check source vs target for [month_start, daily_end)
                        new rows found → EXCEPT INSERT
                        already in sync → skip

Handles retroactive data: if an order from earlier in the month is added to source,
the EXCEPT check detects it and inserts it on the next run.
"""

from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging
from datetime import date, timedelta

from services.core.config import load_config
from services.core.sql import (
    check_exist_table,
    check_data_available,
    render_template,
    execute_sql,
)
from services.core.validate import (
    validate_config,
    validate_identifier,
    validate_logic_date,
    validate_convert_datetime,
    validate_pg,
    validate_sql,
)

log = logging.getLogger(__name__)


def run_star_schema(config_file_name, real_start: date, dataset_start: date, **context):
    """
    Daily operator for star schema backfill with retroactive-data support.

    Args:
        config_file_name : YAML config file in contexts/ directory
        real_start       : date when the DAG first runs in production  (A)
        dataset_start    : first date of the source dataset             (B)
        **context        : Airflow context (provides execution_date)    (C)
    """
    try:
        # 1. Load and validate config
        log.info(f"1. Loading config from {config_file_name}...")
        config = load_config(config_file_name)
        validate_config(config)

        raw_sql_template = config['query']['sql']
        validate_sql(raw_sql_template)

        config_dict = {**config["postgres"], **config["postgres"]["target"]}
        conn_id = schema = table = date_column = None
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
            elif "date_column" in k.lower():
                date_column = v
                validate_identifier(date_column, "date_column")

        log.info(f"Config loaded: conn_id={conn_id}, schema={schema}, table={table}, date_column={date_column}")

        # 2. Compute dataset execution date and SQL window
        log.info("2. Computing dataset execution date...")
        execution_date         = context['execution_date'].date()
        offset                 = (execution_date - real_start).days
        dataset_execution_date = dataset_start + timedelta(days=offset)
        month_start            = dataset_execution_date.replace(day=1)
        daily_end              = dataset_execution_date + timedelta(days=1)

        log.info(
            f"Replay | real_start={real_start} | dataset_start={dataset_start} | "
            f"execution_date={execution_date} | offset={offset}d | "
            f"dataset_execution_date={dataset_execution_date} | "
            f"window=[{month_start} → {daily_end})"
        )

        # 3. Validate date range
        log.info("3. Validating date range...")
        validate_logic_date(
            validate_convert_datetime(month_start),
            validate_convert_datetime(daily_end),
        )

        # 4. Init PostgresHook
        log.info(f"4. Initializing PostgreSQL connection '{conn_id}'...")
        pg_hook = PostgresHook(postgres_conn_id=conn_id)
        validate_pg(pg_hook)

        # 5. Check table existence
        log.info(f"5. Checking table '{schema}.{table}'...")
        is_exist = check_exist_table(pg_hook, schema, table)
        is_dim   = table.lower().startswith("dim")

        # Render source SQL with [month_start, daily_end)
        source_sql = render_template(
            raw_sql_template,
            start_date=str(month_start),
            end_date=str(daily_end),
        )

        # 6. First run: CREATE TABLE AS
        if not is_exist:
            log.info(f"6. Table '{schema}.{table}' does not exist. Running CREATE TABLE AS...")
            create_prefix = render_template(
                config['query']['function']['create'],
                schema=schema,
                table=table,
            )
            execute_sql(pg_hook, f"{create_prefix}\n{source_sql}")
            log.info(f"Table '{schema}.{table}' created successfully.")
            return

        # 7. EXCEPT check: source vs target for [month_start, daily_end)
        log.info(f"7. Checking for new rows in [{month_start} → {daily_end})...")
        if is_dim:
            # Dim has no date column in output — compare source against entire target
            except_check = (
                f"SELECT * FROM ({source_sql}) _new\n"
                f"EXCEPT\n"
                f"SELECT * FROM {schema}.{table}"
            )
        else:
            # Fact: scope target to same [month_start, daily_end) window
            except_check = (
                f"SELECT * FROM ({source_sql}) _new\n"
                f"EXCEPT\n"
                f"SELECT * FROM {schema}.{table}\n"
                f"WHERE {date_column} >= '{month_start}'\n"
                f"AND {date_column} < '{daily_end}'"
            )

        if not check_data_available(pg_hook, except_check):
            log.info(f"[{month_start} → {daily_end}) already in sync. Skipping.")
            return

        # 8. EXCEPT INSERT: only insert rows not already in target
        log.info(f"8. Inserting new rows into '{schema}.{table}'...")
        insert_prefix = render_template(
            config['query']['function']['insert'],
            schema=schema,
            table=table,
        )
        if is_dim:
            insert_sql = (
                f"{insert_prefix}\n"
                f"SELECT * FROM ({source_sql}) _new_rows\n"
                f"EXCEPT\n"
                f"SELECT * FROM {schema}.{table};"
            )
        else:
            insert_sql = (
                f"{insert_prefix}\n"
                f"SELECT * FROM ({source_sql}) _new\n"
                f"EXCEPT\n"
                f"SELECT * FROM {schema}.{table}\n"
                f"WHERE {date_column} >= '{month_start}' AND {date_column} < '{daily_end}';"
            )

        execute_sql(pg_hook, insert_sql)
        log.info(f"Done. New rows inserted into '{schema}.{table}' for [{month_start} → {daily_end}).")

    except Exception as e:
        log.error(f"run_star_schema failed: {str(e)}")
        raise
