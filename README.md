# Olist Capstone — Airflow Server

Apache Airflow pipeline for **E-commerce Data Warehouse** and **KMeans Customer Segmentation** using the [Olist Brazilian E-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).

---

## Architecture Overview

```
Raw Data (public schema)
    │
    ├── Centralization Pipeline ──► centralize schema (Fact & Dim tables)
    │
    └── ML Pipeline
            ├── KMeans Training ──► customer_segmentation.rfm_clusters
            │                  ──► customer_segmentation.ml_artifacts
            │                  ──► customer_segmentation.kmeans_training_log
            │                  ──► customer_segmentation.kmeans_centroid_log
            └── Daily Assign   ──► customer_segmentation.rfm_clusters_daily
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow (Standalone, EC2) |
| Database | PostgreSQL (Supabase) |
| ML | Scikit-learn (KMeans, RobustScaler) |
| Language | Python 3.12 |
| CI/CD | GitHub Actions → SSH → EC2 auto-pull |

---

## Project Structure

```
airflow-server/
├── dags/                              # Airflow DAG definitions
│   ├── centralize_pipeline.py         # Main DWH pipeline (fact + dim tables)
│   ├── operation_centralize_pipeline.py
│   ├── kmeans_training_model.py       # KMeans training DAG
│   └── kmeans_daily_assign.py         # Daily cluster assignment DAG
│
├── plugins/services/                  # Business logic (called by DAGs)
│   ├── kmeans_service.py              # Core KMeans functions
│   ├── kmeans_training_model_orchestration.py
│   ├── kmeans_daily_assign_orchestration.py
│   ├── backfill_orchestration.py
│   ├── backfill_services.py
│   ├── sql_services.py
│   └── validate_services.py
│
├── contexts/                          # YAML configs for each pipeline
│   ├── kmeans_rfm_training.yaml
│   ├── kmeans_rfm_daily.yaml
│   └── centralize/                    # DWH table configs
│       ├── fact_order.yaml
│       ├── fact_order_item.yaml
│       ├── fact_payment.yaml
│       ├── fact_order_review.yaml
│       ├── fact_order_operation.yaml
│       ├── dim_product.yaml
│       ├── dim_user.yaml
│       └── dim_order_review.yaml
│
├── final_kmeans.ipynb                 # KMeans exploration & training notebook
├── Tests/                             # Development & validation notebooks
└── .github/workflows/deploy.yml      # CI/CD: auto-deploy to EC2 on push to main
```

---

## Pipelines

### 1. Data Centralization (ETL)

Backfills and maintains fact/dimension tables in the `centralize` schema.

| Table | Description |
|---|---|
| `fact_order` | Orders with payment and item aggregations |
| `fact_order_item` | Order line items |
| `fact_payment` | Payment breakdown per order |
| `fact_order_review` | Review scores and comments |
| `fact_order_operation` | Operational order statuses |
| `dim_product` | Product dimension |
| `dim_user` | Customer dimension |
| `dim_order_review` | Review dimension |

**Schedule:** `@daily` with `catchup=True` from `2016-09-04`

---

### 2. KMeans Customer Segmentation (ML)

#### Training (`kmeans_training_model.py`)

Trains a KMeans model on historical RFM data and saves artifacts to DB.

| Step | Description |
|---|---|
| Extract | RFM query over training period (2016-09-04 → 2017-02-28) |
| Preprocess | `log1p(monetary)` + `RobustScaler` on `[recency, frequency, monetary]` |
| Find k | Elbow + Silhouette score for k=2..7 |
| Train | `KMeans(n_clusters=3)` |
| Label | Rank centroids → assign champions / potential / at_risk |
| Save | Artifacts, RFM clusters, training metadata, centroid metadata |

#### Daily Assign (`kmeans_daily_assign.py`)

Assigns clusters to customers who purchased on `execution_date` using the pre-trained model.

| Step | Description |
|---|---|
| Load | Scaler + KMeans model from `ml_artifacts` |
| Extract | RFM over rolling 6-month window, triggered by today's buyers |
| Transform | `scaler.transform()` — no retraining |
| Predict | `km.predict()` → cluster assignment |
| Save | Append to `rfm_clusters_daily` with `execution_date` (idempotent) |

#### Segment Labels

| Segment | Recency | Frequency | Monetary |
|---|---|---|---|
| **champions** | Low (recent) | Highest | Highest |
| **potential** | Low (recent) | Medium | Medium |
| **at_risk** | High (inactive) | Lowest | Lowest |

---

## Database Schema

```
customer_segmentation
├── ml_artifacts           # Pickled scaler + kmeans model (upsert by name)
├── rfm_clusters           # Training baseline — replaced on retrain
├── rfm_clusters_daily     # Daily assignments — append with execution_date
├── kmeans_training_log    # Model metrics per training run
└── kmeans_centroid_log    # Centroid positions per training run
```

---

## Configuration

Each pipeline reads from a YAML config in `contexts/`. Example for KMeans daily:

```yaml
# contexts/kmeans_rfm_daily.yaml
postgres:
  conn_id: supermarket
  daily:
    schema: customer_segmentation
    table: rfm_clusters_daily
    query: |
      select customer_unique_id, recency, frequency, monetary
      ...
  artifact:
    query: |
      select artifact_data from ml_artifacts where artifact_name = :artifact_name
```

---

## Deployment

Pushes to `main` branch automatically deploy to EC2 via GitHub Actions:

```
git push origin main
    └── GitHub Actions
            └── SSH to EC2
                    └── git pull origin main
                            └── Airflow auto-reloads DAGs
```

**Required GitHub Secrets:**

| Secret | Description |
|---|---|
| `EC2_HOST` | EC2 public IP or hostname |
| `EC2_USERNAME` | SSH username |
| `EC2_PRIVATE_KEY` | SSH private key |
| `EC2_PORT` | SSH port |
| `AIRFLOW_PROJECT_PATH` | Absolute path on EC2 |

---

## Local Development

```bash
# 1. Clone repo
git clone <repo-url>
cd airflow-server

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install apache-airflow scikit-learn pandas sqlalchemy psycopg2-binary pyyaml python-dotenv

# 4. Set environment variables
cp .env.example .env
# Fill in DATABASE, USER, PASSWORD, HOST, PORT, SUPABASE_URL, SUPABASE_KEY

# 5. Run exploration notebook
jupyter notebook final_kmeans.ipynb
```
