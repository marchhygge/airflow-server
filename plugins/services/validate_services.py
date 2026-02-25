"""
Docstring for services.validate_service
This file contains utility functions for validating input parameters.
"""
from datetime import datetime, date as date_type
import re
import logging

log = logging.getLogger(__name__)

def validate_backfill_config(config):
    """
    Validate the structure and content of the configuration dictionary.
    Args:
    - config: dict, the configuration to validate
        Raises:
    - ValueError: If any validation fails, with a descriptive error message
    """
    try:
        log.info("Validating config structure...")
        
        # Validate top-level keys
        required_keys = ["postgres", "query"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Config missing required key: '{key}'")
        
        # Validate postgres section
        postgres_config = config["postgres"]
        if "conn_id" not in postgres_config:
            raise ValueError("Config 'postgres.conn_id' is required")
        if "target" not in postgres_config:
            raise ValueError("Config 'postgres.target' is required")
        
        target = postgres_config["target"]
        
        # Validate required target fields
        required_target_fields = ["schema", "table", "start_date", "end_date", "date_column"]
        for field in required_target_fields:
            if field not in target or target[field] is None:
                raise ValueError(f"Config 'postgres.target.{field}' is required and cannot be empty")
        
        # Validate query section
        query = config["query"]
        if "sql" not in query or not query["sql"]:
            raise ValueError("Config 'query.sql' is required and cannot be empty")
        if "function" not in query:
            raise ValueError("Config 'query.function' is required")
        
        function = query["function"]
        if "create" not in function or "insert" not in function:
            raise ValueError("Config 'query.function' must have 'create' and 'insert' sections")
        
        log.info("Configuration validation successful")
        return True
        
    except Exception as e:
        log.error(f"Configuration validation failed: {str(e)}")
        raise

# Validate postgre connection
def validate_pg(pg_hook):
    if pg_hook is None:
        raise ValueError("pg_hook cannot be None")

# Validate SQL
def validate_sql(sql):
    if not sql or not isinstance(sql, str):
        raise ValueError("sql must be a non-empty string")

# validate string
def validate_identifier(name, label="identifier"):
    # Validate that the name is a non-empty string
    if not name or not isinstance(name, str):
        raise ValueError(f"{label} must be a non-empty string")
    
    # Validate that the name does not exceed typical identifier length limits (e.g., 63 characters for PostgreSQL)
    if len(name) > 63:
        raise ValueError(f"{label} '{name}' exceeds maximum length of 63 characters")
    
    # Validate that the name starts with a letter or underscore and contains only valid characters (letters, digits, underscores)
    if not re.match(r"^[a-z_][a-z0-9_-]*$", name.lower()):
        raise ValueError(
            f"Invalid {label}: '{name}'. "
            f"Must start with letter or underscore, "
            f"contain only letters, numbers, underscore, hyphen. "
            f"Example: 'dim_user', 'fact_order', 'order_date'"
        )
    
    # Validate that the name starts with a letter or underscore and contains only valid characters (letters, digits, underscores)
    sql_keywords = {
        'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter',
        'truncate', 'grant', 'revoke', 'union', 'join', 'where', 'from',
        'order', 'group', 'having', 'limit', 'offset', 'distinct'
    }
    if name.lower() in sql_keywords:
        raise ValueError(f"{label} '{name}' is a reserved SQL keyword - cannot use")
    
    # Validate that the name does not contain dangerous characters to prevent SQL injection
    dangerous_chars = {';', "'", '"', '--', '/*', '*/', 'xp_', 'sp_'}
    for char in dangerous_chars:
        if char in name.lower():
            raise ValueError(
                f"Invalid {label}: '{name}' contains dangerous character: '{char}'"
            )

# Validate logic date
def validate_logic_date(start_date, end_date):
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date. Check yaml config.")

# Validate and convert datetime
def validate_convert_datetime(value):
    if isinstance(value, datetime):
        return value
    
    if isinstance(value, date_type):
        return datetime.combine(value, datetime.min.time())
    
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except Exception as e:
            raise ValueError(f"Invalid date string: {value}. Error: {str(e)}")
    raise ValueError(f"Unsupported date type: {type(value)}. Must be datetime, date, or string in YYYY-MM-DD format.")