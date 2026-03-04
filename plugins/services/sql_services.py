"""
Docstring for services.sql_service
This file contains utility functions for SQL database operations.
"""
import jinja2
from jinja2 import Template
from services.validate_services import *
import logging

log = logging.getLogger(__name__)

# Check exist table
def check_exist_table(pg_hook, schema, table_name):
    """
        Check if a table exists in the database.
        
        args:
            pg_hook: PostgreSQL hook connection
            table_name: Name of the table to check

        returns:
            bool: True if table exists, False otherwise

        raises:
            ValueError: If inputs are invalid
    """
    try:
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
def get_max_date(pg_hook, schema, table_name, based_on_table, date_column):
    """
        Get the maximum date from a date column in the specified table.
        
        args:
            pg_hook: PostgreSQL hook connection
            table_name: Name of the table to query
            based_on_table: Name of the table that defines the date column to use
            date_column: Name of the date column to get max value from
        returns:
            datetime: Maximum date found in the table
        raises:
            ValueError: If inputs are invalid
    """
    try:
        log.info(f"getting max {date_column} from table '{schema}.{table_name}'...")

        if table_name.lower().startswith("fact"):
            table = table_name
        elif table_name.lower().startswith("dim"):
            if based_on_table == None:
                raise ValueError(f"It's a dim table, but no based_on_table provided, add based_on: table_name in target config to specify the table to get max {date_column}.")
            table = based_on_table
            log.info(f"Dim table detected. Using based_on_table '{table}' to get max {date_column}...")
        else:
            raise ValueError(f"Invalid table name '{table_name}'. Table name should start with 'fact' or 'dim'.")
            
        sql = f"SELECT MAX({date_column}) FROM {schema}.{table};"
        result = pg_hook.get_first(sql)
        return result[0] if result else None
    
    except Exception as e:
        log.error(f"Error getting max {date_column} from table '{table}': {str(e)}")
        raise

# Check data available
def check_data_available(pg_hook, sql):
    """
        Check if data is available for the given SQL query.
        args:
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
        args:
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
        return result
    
    # Handle specific Jinja2 template syntax errors (ex: missing closing tag, undefined variables, etc.)
    except jinja2.exceptions.TemplateSyntaxError as e:
        log.error(f"Invalid Jinja2 template syntax at line {e.lineno}: {str(e)}")
        raise

    # Handle missing variables in template rendering (ex: if raw_sql contains {{schema}} but it's not provided in kwargs)
    except ValueError as e:
        log.error(f"Validation error: {str(e)}")
        raise

    # Handle any other unexpected exceptions during template rendering
    except Exception as e:
        log.error(f"Unexpected error rendering SQL template: {str(e)}")
        raise

# excute function
def execute_sql(pg_hook, sql):
    """
        Execute a SQL command.
        args:
            pg_hook: PostgreSQL hook connection
            sql: SQL command to execute
        returns:
            None
        raises:
            ValueError: If inputs are invalid
    """
    try:
        log.info("Executing SQL query...")
        pg_hook.run(sql)
        log.info("SQL executed successfully.")
    except Exception as e:
        log.error(f"Error executing SQL: {str(e)}")
        raise