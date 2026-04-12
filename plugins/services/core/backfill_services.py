"""
This module provides helper functions for backfill operations, including SQL generation and date calculations.
"""

from datetime import datetime
from dateutil.relativedelta import relativedelta
from services.core.sql import get_max_date

# Resolve raw SQL based on table existence
def resolve_raw_sql(config, is_exist, table_name=None):
    """
    Decide CREATE or INSERT SQL block.
    - First run (table not exist): CREATE TABLE AS ... + raw_sql
    - Fact re-run: INSERT INTO ... + raw_sql
    - Dim re-run: INSERT INTO ... SELECT * FROM (raw_sql) EXCEPT SELECT * FROM existing table
      Dim tables have no date column in their output, so DELETE-range approach would fail.
      EXCEPT ensures only new rows are inserted — idempotent without needing a unique key.
    """
    insert_block = config['query']['function']['insert'] + '\n' + config['query']['sql']

    if not is_exist:
        return config['query']['function']['create'] + '\n' + config['query']['sql']

    if table_name and table_name.lower().startswith("dim_"):
        raw_sql = config['query']['sql'].rstrip().rstrip(';')
        except_insert = (
            config['query']['function']['insert'] + "\n"
            "SELECT * FROM (\n"
            + raw_sql + "\n"
            ") _new_rows\n"
            "EXCEPT\n"
            "SELECT * FROM {{ schema }}.{{ table }};"
        )
        return except_insert

    return insert_block

# Resolve start date for backfill
def resolve_start_date_dt(table_name, max_date, default_date, is_exist):
    """
    input:
    - table_name: name of the target table from yaml config
    - max_date:  from services.core.sql.get_max_date function
    - default_date: the default start date from yaml config
    - is_exist: from services.core.sql.check_exist_table function

    Process:
    - If table NOT exist: use default_date
    - If table exist but max_date is None: use default_date
    - If table exist and max_date exists:
      - For fact table: max_date + 1 month (next month after last data)
      - For dim table: max_date (same month as fact table)

    Output:
    - final_date: the resolved start date for backfill process
    """
    # If table does not exist or max_date is None, start from default_date
    if not is_exist or max_date is None:
        return default_date

    # Convert max_date to datetime
    if not isinstance(max_date, datetime):
        max_date = datetime.combine(max_date, datetime.min.time())

    if table_name.lower().startswith("fact_"):
        return max_date + relativedelta(months=1)
    else:
        return max_date

# Build SQL for a single backfill month
def build_sql_for_month(raw_sql, schema, table, start_date_dt, render_template, date_column=None):
    """
    Input:
    - raw_sql: query from yaml config
    - schema: schema name from yaml config
    - table: table name from yaml config
    - start_date_dt: the start date for this backfill iteration (datetime object)
    - render_template: function to render SQL with parameters
    - date_column: optional, required when raw_sql contains {{ date_column }} (e.g. dim DELETE block)

    Process:
    - Calculate end_date_dt as start_date_dt + 1 month
    - Render the SQL template with schema, table, start_date, end_date, and optionally date_column

    Output:
    - rendered_sql: the final SQL string ready for execution
    """
    end_date_dt = start_date_dt + relativedelta(months=1)

    kwargs = dict(
        schema=schema,
        table=table,
        start_date=start_date_dt.strftime("%Y-%m-01"),
        end_date=end_date_dt.strftime("%Y-%m-01")
    )
    if date_column:
        kwargs['date_column'] = date_column

    return render_template(raw_sql, **kwargs)

# build SQL for a single day
def build_sql_for_day(raw_sql, schema, table, process_date, render_template) -> str:
    """
    Input:
    - raw_sql: query from yaml config
    - schema: schema name from yaml config
    - table: table name from yaml config
    - process_date: the process date for this backfill iteration (datetime object)
    - render_template: function to render SQL with parameters

    Process:
    - Calculate end_date_dt as process_date + 1 day
    - Render the SQL template with schema, table, start_date, and end_date

    Output:
    - rendered_sql: the final SQL string ready for execution
    """
    end_date = process_date + relativedelta(days=1)

    return render_template(
        raw_sql,
        schema=schema,
        table=table,
        start_date=process_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d")
    )
    
