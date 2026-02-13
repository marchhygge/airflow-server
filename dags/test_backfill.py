from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
from functools import partial
from services.backfill_orchestration import run_backfill

with DAG(
    dag_id="fact_order_test_backfill",
    start_date=datetime(2026, 2, 1, 9, 0),
    schedule="@daily",
    catchup=True,
    max_active_runs=1,
    tags=["test", "backfill"],  
) as dag:

    # Specify config file name here
    config_file = "test_write_pg.yaml"
    
    run = PythonOperator(
        task_id="run_backfill",
        python_callable=partial(run_backfill, config_file_name=config_file),
        depends_on_past=True, 
    )