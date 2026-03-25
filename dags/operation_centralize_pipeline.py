from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from datetime import date, datetime
from functools import partial
from services.orchestrations.operation import run_operation

with DAG(
    dag_id="operation_centralize_pipeline",
    start_date=datetime(2016, 9, 3, 9, 0),
    end_date=datetime(2016, 12, 31),
    schedule="@daily", # first run = start_date + 1 days
    catchup=True,
    max_active_runs=3,
    tags=["centralize", "operation", "test"],  
) as dag:

    # fact_order_operation task
    fact_order = PythonOperator(
        task_id="fact_order_operation",
        python_callable=partial(run_operation, config_file_name="centralize/fact_order_operation.yaml"),
        depends_on_past=True, 
    )
    
    # create start and end dummy tasks for better visualization
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    start >> [fact_order] >> end