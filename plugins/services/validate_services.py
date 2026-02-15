"""
Docstring for services.validate_service
This file contains utility functions for validating input parameters.
"""
from datetime import datetime, date as date_type

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
    if not name or not isinstance(name, str):
        raise ValueError(f"{label} must be a non-empty string")

# Validate logic date
def validate_logic_date(start_date, end_date):
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")

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