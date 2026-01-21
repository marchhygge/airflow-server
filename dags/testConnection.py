from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime

def test_supermarket_conn():
    hook = PostgresHook(postgres_conn_id="supermarket")
    result = hook.get_first("select * from customers limit 10")
    print(result)

with DAG(
    dag_id="test_supermarket_connection",
    start_date =datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
) as dag:
    PythonOperator(
        task_id="test_pg_conn",
        python_callable=test_supermarket_conn,
    )