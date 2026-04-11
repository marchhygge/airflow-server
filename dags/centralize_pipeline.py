from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from datetime import datetime, date
from services.orchestrations.backfill import run_backfill

REPLAY = {
    "real_start":    date(2026, 4, 1),   # Real start date
    "dataset_start": date(2016, 9, 4),   # first order date in dataset, also the first date to backfill
}

with DAG(
    dag_id="centralize_pipeline_backfill",
    start_date=datetime(2026, 4, 1),  # midnight → first execution_date = 2026-04-01
    schedule="@daily",
    catchup=True,
    max_active_runs=1,
    tags=["centralize", "backfill"],
) as dag:

    fact_order = PythonOperator(
        task_id="fact_order",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/fact_order.yaml"},
        depends_on_past=True,
    )

    fact_order_item = PythonOperator(
        task_id="fact_order_item",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/fact_order_item.yaml"},
        depends_on_past=True,
    )

    fact_payment = PythonOperator(
        task_id="fact_payment",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/fact_payment.yaml"},
        depends_on_past=True,
    )

    fact_order_review = PythonOperator(
        task_id="fact_order_review",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/fact_order_review.yaml"},
        depends_on_past=True,
    )

    dim_product = PythonOperator(
        task_id="dim_product",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/dim_product.yaml"},
        depends_on_past=True,
    )

    dim_order_review = PythonOperator(
        task_id="dim_order_review",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/dim_order_review.yaml"},
        depends_on_past=True,
    )

    dim_user = PythonOperator(
        task_id="dim_user",
        python_callable=run_backfill,
        op_kwargs={**REPLAY, "config_file_name": "centralize/dim_user.yaml"},
        depends_on_past=True,
    )

    # create start and end dummy tasks for better visualization
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    start >> [fact_order, fact_order_item, fact_payment, fact_order_review] 
    fact_order >> [dim_product, dim_order_review, dim_user] >> end