"""
Docstring for services.validate_service
This file contains utility functions for validating input parameters.
"""

def validate_pg(pg_hook):
    if pg_hook is None:
        raise ValueError("pg_hook cannot be None")

def validate_sql(sql):
    if not sql or not isinstance(sql, str):
        raise ValueError("sql must be a non-empty string")

def validate_identifier(name, label="identifier"):
    if not name or not isinstance(name, str):
        raise ValueError(f"{label} must be a non-empty string")
