from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from datetime import datetime

with DAG(
    dag_id="Execution_date_test",
    description="Sample DAG to test Git CI/CD with Airflow Standalone",
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2025, 1, 1),
    schedule_interval="@daily",
    catchup=True,
    tags=["test", "thinhh"],
) as dag:

    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    def my_task(**context):
        execution_date = context["ds"]
        print("Execution date:", execution_date)

    task = PythonOperator(
        task_id="print_date",
        python_callable=my_task,
        depend_on_past=True,
)

start >> task >> end
