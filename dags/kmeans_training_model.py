from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from datetime import date, datetime
from functools import partial
from services.kmeans_training_model_orchestration import customer_segmentation_model_training

with DAG(
    dag_id="kmeans_training_model",
    start_date=datetime(2026, 3, 19, 9, 0),
    end_date=datetime(2026, 3, 20, 9, 0),
    schedule="@daily", # first run = start_date + 1 days
    catchup=True,
    max_active_runs=1,
    tags=["machine learning", "training model", "test"],  
) as dag:

    kmeans_training = PythonOperator(
        task_id="train_kmeans_model",
        python_callable=partial(customer_segmentation_model_training, config_file_name="kmeans_rfm_training.yaml"),
        depends_on_past=True, 
    )
    
    # create start and end dummy tasks for better visualization
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    start >> [kmeans_training] >> end