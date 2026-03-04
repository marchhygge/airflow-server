"""
This module contains utility functions for Airflow DAGs, such as retrieving the execution date.
"""

# Get the execution date from the Airflow context
def get_execution_date(**context):
    execution_date = context["ds"]
    return execution_date