"""
Docstring for services.validate_service
This file contains utility functions for validating input parameters.
"""

# this function validates input parameters for a input validation service
def validate_inputs(pg_hook, job_name):
    """Validate input parameters"""
    if pg_hook is None:
        raise ValueError("pg_hook cannot be None")
    
    if not job_name or not isinstance(job_name, str):
        raise ValueError("job_name must be a non-empty string")
    
    if job_name.strip() == "":
        raise ValueError("job_name cannot be empty or whitespace")