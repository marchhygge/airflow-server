from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from datetime import date, datetime
from functools import partial
from services.kmeans_daily_assign_orchestration import customer_segmentation_daily_assign

with DAG(
    dag_id="kmeans_daily_assign_pipeline",
    start_date=datetime(2017, 2, 28, 9, 0),
    end_date=datetime(2017, 3, 10),
    schedule="@daily", # first run = start_date + 1 days
    catchup=True,
    max_active_runs=1,
    tags=["machine learning", "daily assignment", "test"],  
) as dag:

    kmeans_daily_assign = PythonOperator(
        task_id="daily_assign_clusters",
        python_callable=partial(customer_segmentation_daily_assign, config_file_name="kmeans_rfm_daily.yaml"),
        depends_on_past=True, 
    )
    
    # create start and end dummy tasks for better visualization
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    start >> [kmeans_daily_assign] >> end