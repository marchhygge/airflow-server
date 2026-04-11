from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from datetime import datetime
from functools import partial
from services.orchestrations.kmeans_daily import customer_segmentation_daily_assign

context_file = "kmeans_rfm_daily.yaml"
with DAG(
    dag_id="kmeans_daily_assign_pipeline",
    start_date=datetime(2026, 4, 1),  # real_start: ngày đầu tiên chạy production
    schedule="@daily",
    catchup=True,   # backfill tuần tự từ start_date, depends_on_past giữ đúng thứ tự
    max_active_runs=1,
    tags=["machine learning", "daily assignment"],
) as dag:

    kmeans_daily_assign = PythonOperator(
        task_id="daily_assign_clusters",
        python_callable=partial(customer_segmentation_daily_assign, config_file_name=context_file),
        depends_on_past=True, 
    )
    
    # create start and end dummy tasks for better visualization
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    start >> [kmeans_daily_assign] >> end