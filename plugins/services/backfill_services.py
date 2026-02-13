"""
This module provides helper functions for backfill operations, including SQL generation and date calculations.
"""

from datetime import datetime
from dateutil.relativedelta import relativedelta
from services.sql_services import get_max_date


def resolve_raw_sql(config, is_exist):
    """
    Decide CREATE or INSERT SQL block
    """
    if not is_exist:
        return config['query']['function']['create'] + '\n' + config['query']['sql']
    return config['query']['function']['insert'] + '\n' + config['query']['sql']


def resolve_start_date_dt(pg_hook, schema, table, default_date, is_exist):
    """
    Decide backfill start month
    """
    if not is_exist:
        return default_date

    max_date = get_max_date(pg_hook, schema, table)
    if not max_date:
        raise ValueError(f"Table {schema}.{table} exists but max_date is NULL")

    if not isinstance(max_date, datetime):
        max_date = datetime.combine(max_date, datetime.min.time())

    return max_date + relativedelta(months=1)


def build_sql_for_month(raw_sql, schema, table, start_date_dt, render_template):
    """
    Render SQL for a single backfill month
    """
    end_date_dt = start_date_dt + relativedelta(months=1)

    return render_template(
        raw_sql,
        schema=schema,
        table=table,
        start_date=start_date_dt.strftime("%Y-%m-01"),
        end_date=end_date_dt.strftime("%Y-%m-01")
    )
