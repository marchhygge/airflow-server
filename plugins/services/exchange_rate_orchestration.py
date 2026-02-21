import requests
import pandas as pd
from services.api_services import (
    validate_api_status,
    load_config,
    get_api_key,
    load_df_to_postgres
)

def get_quota_info(config_file_name):
    """
    Docstring for get_quota_info as a function to get quota information from API
    Args:
    - config_file_name: str, the name of the config file in contexts directory
    Returns:
    - dict: The JSON data from the API response if the request is successful and the API indicates success.
    Raises:
    - ValueError: If the API response indicates an error or if the response structure is unexpected.
    - RuntimeError: If the API request times out.
    """
    # Load config, get API key, and construct API URL
    config = load_config(config_file_name)
    url = f"{config['api']['base_url']}/{config['api']['quota_end_point']}"
    api_key = get_api_key()

    try: 
        # Make API request and validate response
        response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        
        # Validate API response and extract data
        data = validate_api_status(response, config["api"]["error_messages"])
        
        print(f"Quota Info - Plan: {data.get('plan_quota')}, Remaining: {data.get('requests_remaining')}")
        return data
        
    except requests.exceptions.Timeout:
        raise RuntimeError("API Request timed out")

def get_exchange_rates_df(config_file_name):
    """
    Docstring for get_exchange_rates_df as a function to get exchange rates from API and load to PostgreSQL
    Args:
    - config_file_name: str, the name of the config file in contexts directory
    Returns:
    - int: The number of exchange rates loaded into the PostgreSQL table.
    Raises:
    - ValueError: If the API response indicates an error or if the response structure is unexpected
    - RuntimeError: If the API request times out.
    """
    # Load config, get API key, and construct API URL
    config = load_config(config_file_name)
    url = f"{config['api']['base_url']}/{config['api']['exchange_rate_end_point']}"
    api_key = get_api_key()
    db_config = config["postgres"]

    try: 
        # Make API request and validate response
        response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        
        # Validate API response and extract data
        data = validate_api_status(response, config["api"]["error_messages"])
        
        # Create DataFrame from conversion rates and load to PostgreSQL
        df = pd.DataFrame(list(data["conversion_rates"].items()), columns=["Currency", "Rate"])
        load_df_to_postgres(
            dataframe=df, 
            conn_id=db_config["conn_id"], 
            schema=db_config["target"]["schema"], 
            table_name=db_config["target"]["table"]
        )
        return len(df) 
        
    except requests.exceptions.Timeout:
        raise RuntimeError("API Request timed out")
