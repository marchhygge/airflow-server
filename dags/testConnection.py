from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime
from tabulate import tabulate

def test_supermarket_conn():
    hook = PostgresHook(postgres_conn_id="supermarket")
    df = hook.get_pandas_df("""
        select * 
        from customers 
        limit 10
    """)
    table = tabulate(
        df,
        headers='keys',
        tablefmt='psql',
        showindex=False
    )
    print(table)

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