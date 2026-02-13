"""
Docstring for services.sql_service
This file contains utility functions for SQL database operations.
"""

from jinja2 import Template
from services.validate_service import validate_inputs
import logging

log = logging.getLogger(__name__)

# Check exist table
def check_exist_table(pg_hook, schema, table_name):
    """
        Check if a table exists in the database.
        
        agrs:
            pg_hook: PostgreSQL hook connection
            table_name: Name of the table to check

        returns:
            bool: True if table exists, False otherwise

        raises:
            ValueError: If inputs are invalid
    """
    try:
        validate_inputs(pg_hook, table_name)

        query = """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                AND table_name = %s
            );
        """
        result = pg_hook.get_first(query, parameters=(schema, table_name))
        return result[0]
    except Exception as e:
        log.error(f"Error checking existence of table '{table_name}': {str(e)}")
        raise

# Get max date
def get_max_date(pg_hook, schema, table_name):
    """
        Get the maximum date from a date column in the specified table.
        
        agrs:
            pg_hook: PostgreSQL hook connection
            table_name: Name of the table to query
        returns:
            datetime: Maximum date found in the table
        raises:
            ValueError: If inputs are invalid
    """
    try:
        sql = f"SELECT MAX(date_column) FROM {schema}.{table_name};"
        result = pg_hook.get_first(sql)
    except Exception as e:
        log.error(f"Error getting max date from table '{table_name}': {str(e)}")

# render function
def render_template(raw_sql, **kwargs):
    """
        Render a SQL template with provided parameters.
        agrs:
            raw_sql: Raw SQL string with Jinja2 templates
            kwargs: parameters for template rendering
        returns:
            str: Rendered SQL string
        raises:
            ValueError: If inputs are invalid
    """
    try:
        result = Template(raw_sql).render(**kwargs)
        if not result:
            raise ValueError("Rendered SQL is empty")
        
        return result
    except Exception as e:
        log.error(f"Error rendering SQL template: {str(e)}")
        raise  

# excute function
def execute_sql(pg_hook, sql):
    """
        Execute a SQL command.
        
        agrs:
            pg_hook: PostgreSQL hook connection
            sql: SQL command to execute

        returns:
            None

        raises:
            ValueError: If inputs are invalid
    """
    try:
        validate_inputs(pg_hook, sql)
        pg_hook.run(sql)
        log.info("SQL executed successfully.")
    except Exception as e:
        log.error(f"Error executing SQL: {str(e)}")
        raise