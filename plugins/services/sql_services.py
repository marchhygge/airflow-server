"""
Docstring for services.sql_service
This file contains utility functions for SQL database operations.
"""

from jinja2 import Template
from services.validate_service import *
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
        log.info("Validating inputs for table existence check...")
        validate_identifier(table_name, "table_name")
        log.info(f"Checking existence of table '{schema}.{table_name}'...")
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
        log.info(f"getting max date from table '{schema}.{table_name}'...")
        sql = f"SELECT MAX(report_date) FROM {schema}.{table_name};"
        result = pg_hook.get_first(sql)
        return result[0] if result else None
    except Exception as e:
        log.error(f"Error getting max date from table '{table_name}': {str(e)}")
        raise

# Check data available
def check_data_available(pg_hook, sql):
    """
        Check if data is available for the given SQL query.
        
        agrs:
            pg_hook: PostgreSQL hook connection
            sql: SQL query to check for data availability
        returns:
            bool: True if data is available, False otherwise
        raises:
            ValueError: If inputs are invalid
    """
    sql = f"select 1 from ({sql}) limit 1;"
    try:
        log.info("Checking data availability with SQL query...")
        exist = pg_hook.get_first(sql)
        if exist:
            return True
        else:
            return False
    except Exception as e:
        log.error(f"Error checking data availability: {str(e)}")
        raise

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
        log.info("Rendering SQL query with parameters...")
        result = Template(raw_sql).render(**kwargs)
        if not result:
            raise ValueError("Rendered SQL is empty")
        else:
            log.info("SQL query rendered successfully")
            log.info(f"Rendered SQL: {result}")
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
        log.info("Validating inputs for SQL execution...")
        validate_sql(sql)
        log.info("Executing SQL query...")
        pg_hook.run(sql)
        log.info("SQL executed successfully.")
    except Exception as e:
        log.error(f"Error executing SQL: {str(e)}")
        raise