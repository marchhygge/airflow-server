from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
from functools import partial
from services.exchange_rate_orchestration import (
    get_exchange_rates_df,
    get_quota_info
)

with DAG(
    dag_id="exchange_rate_test",
    start_date= datetime(2026, 2, 21, 10, 0),
    schedule="@daily",
    catchup=False, # Set to False to avoid backfilling when the DAG is first deployed
    max_active_runs=1,
    depends_on_past=True, 
    tags=["exchange_rate","test"]
) as dag:
    
    quota_info = PythonOperator(
        task_id = "get_quota_info",
        python_callable=partial(get_quota_info, config_file_name="exchange_rate.yaml")
    )

    exchange_rate = PythonOperator(
        task_id = "get_exchange_rates",
        python_callable=partial(get_exchange_rates_df, config_file_name="exchange_rate.yaml")
    )

    quota_info >> exchange_rate
