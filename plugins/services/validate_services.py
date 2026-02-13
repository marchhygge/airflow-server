"""
Docstring for services.validate_service
This file contains utility functions for validating input parameters.
"""

# this function validates input parameters for a input validation service
def validate_pg_and_sql(pg_hook, sql):
    if pg_hook is None:
        raise ValueError("pg_hook cannot be None")
    if not sql or not isinstance(sql, str):
        raise ValueError("sql must be a non-empty string")