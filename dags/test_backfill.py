from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
from services.backfill_service import run_backfill

with DAG(
    dag_id="fact_order_test_backfill_one_month_per_day",
    start_date=datetime(2026, 1, 22, 9, 0),
    schedule="@daily",
    catchup=False,
    depend_on_past=True,
    tags=["test", "backfill"],
) as dag:

    run = PythonOperator(
        task_id="run_backfill",
        python_callable=run_backfill
    )


