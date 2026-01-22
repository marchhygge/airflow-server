"""
this file is used to manage checkpoint data
1. Get last processed month
2. get_next_month
3. update last processed month

Goal:
- To keep track of the last processed month before processing data pipelines.
"""

from dateutil.relativedelta import relativedelta
from datetime import datetime
import logging

log = logging.getLogger(__name__)


def validate_inputs(pg_hook, job_name):
    """Validate input parameters"""
    if pg_hook is None:
        raise ValueError("pg_hook cannot be None")
    
    if not job_name or not isinstance(job_name, str):
        raise ValueError("job_name must be a non-empty string")
    
    if job_name.strip() == "":
        raise ValueError("job_name cannot be empty or whitespace")


def get_last_processed_month(pg_hook, job_name):
    """
    Get last processed month from checkpoint table
    
    Args:
        pg_hook: PostgreSQL hook connection
        job_name: Name of the job
        
    Returns:
        datetime: Last processed month
        
    Raises:
        ValueError: If inputs are invalid or job_name not found
    """
    try:
        validate_inputs(pg_hook, job_name)
        
        # Use parameterized query to prevent SQL injection
        query = """
            SELECT last_processed_month
            FROM centralize.backfill_checkpoint
            WHERE job_name = %s
        """
        result = pg_hook.get_first(query, parameters=(job_name,))
        
        if result is None or len(result) == 0:
            raise ValueError(f"Job '{job_name}' not found in checkpoint table")
        
        last_processed_month = result[0]
        
        if last_processed_month is None:
            raise ValueError(f"last_processed_month is NULL for job '{job_name}'")
        
        # Validate it's a datetime object
        if not isinstance(last_processed_month, datetime):
            raise TypeError(f"Expected datetime object, got {type(last_processed_month)}")
        
        log.info(f"Retrieved last_processed_month for job '{job_name}': {last_processed_month}")
        return last_processed_month
        
    except Exception as e:
        log.error(f"Error getting last_processed_month for job '{job_name}': {str(e)}")
        raise


def get_next_month(last_processed_month):
    """
    Calculate next month start and end dates
    
    Args:
        last_processed_month: datetime object
        
    Returns:
        tuple: (month_start, month_end) as datetime objects
        
    Raises:
        TypeError: If last_processed_month is not a datetime object
    """
    try:
        if not isinstance(last_processed_month, datetime):
            raise TypeError(f"last_processed_month must be datetime object, got {type(last_processed_month)}")
        
        month_start = last_processed_month + relativedelta(months=1)
        month_end = month_start + relativedelta(months=1)
        
        # Ensure month_start is first day of month
        if month_start.day != 1:
            month_start = month_start.replace(day=1)
        
        log.info(f"Calculated next month: {month_start} to {month_end}")
        return month_start, month_end
        
    except Exception as e:
        log.error(f"Error calculating next month: {str(e)}")
        raise


def update_last_processed_month(pg_hook, job_name, last_processed_month):
    """
    Update last processed month in checkpoint table
    
    Args:
        pg_hook: PostgreSQL hook connection
        job_name: Name of the job
        last_processed_month: datetime object to update
        
    Raises:
        ValueError: If inputs are invalid
    """
    try:
        validate_inputs(pg_hook, job_name)
        
        if not isinstance(last_processed_month, datetime):
            raise TypeError(f"last_processed_month must be datetime object, got {type(last_processed_month)}")
        
        # Ensure month_start is first day of month
        month_str = last_processed_month.replace(day=1).strftime('%Y-%m-01')
        
        # Use parameterized query to prevent SQL injection
        query = """
            UPDATE centralize.backfill_checkpoint
            SET last_processed_month = %s
            WHERE job_name = %s
        """
        pg_hook.run(query, parameters=(month_str, job_name))
        
        log.info(f"Updated checkpoint for job '{job_name}': {month_str}")
        
    except Exception as e:
        log.error(f"Error updating last_processed_month for job '{job_name}': {str(e)}")
        raise