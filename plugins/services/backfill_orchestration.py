import yaml
from datetime import datetime
from pathlib import Path
from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging
from dateutil.relativedelta import relativedelta
from services.sql_services import (
    check_exist_table,
    check_data_available,
    render_template,
    execute_sql
)
from services.backfill_services import (
    resolve_raw_sql,
    resolve_start_date_dt,
    build_sql_for_month
)

log = logging.getLogger(__name__)

CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"


def run_backfill(config_file_name):
    try:
        # 1. Load config
        config_path = str(Path(CONTEXTS_DIR) / config_file_name)
        with open(config_path) as f:
            config = yaml.safe_load(f)

        raw_sql = config['query']['sql']
        config_dict = {**config["postgres"], **config["postgres"]["target"]}

        conn_id = schema = table = date = None
        for k, v in config_dict.items():
            if isinstance(v, dict):
                continue
            if "con" in k.lower():
                conn_id = v
            elif "schema" in k.lower():
                schema = v
            elif "table" in k.lower():
                table = v
            elif "date" in k.lower():
                date = v
        log.info(f"Config loaded: conn_id={conn_id}, schema={schema}, table={table}, date={date}")

        if not isinstance(date, datetime):
            date = datetime.combine(date, datetime.min.time())

        # 2. Init Postgres hook
        pg_hook = PostgresHook(postgres_conn_id=conn_id)

        # 3. Check table
        is_exist = check_exist_table(pg_hook, schema, table)

        # 4. Resolve SQL & start date
        process_sql = resolve_raw_sql(config, is_exist)
        start_date_dt = resolve_start_date_dt(pg_hook, schema, table, date, is_exist)

        # 5. Backfill loop
        max_run = 24
        current_run = 0
        while current_run < max_run:
            sql = build_sql_for_month(process_sql, schema, table, start_date_dt, render_template)
            raw_sql = build_sql_for_month(raw_sql, schema, table, start_date_dt, render_template)

            if is_exist and not check_data_available(pg_hook, raw_sql):
                log.info(f"No data for {start_date_dt:%Y-%m}, skipping")
                start_date_dt += relativedelta(months=1)
                current_run += 1
                continue

            execute_sql(pg_hook, sql)
            log.info(f"Backfill success for {start_date_dt:%Y-%m}")
            break

        raise ValueError("No data found after max backfill window")

    except Exception as e:
        log.error(f"Backfill failed: {str(e)}")
        raise
