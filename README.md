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
│   ├── exchange_rate_test.py
│   ├── kmeans_training_model.py       # KMeans training DAG
│   └── kmeans_daily_assign.py         # Daily cluster assignment DAG
│
├── plugins/services/                  # Business logic (called by DAGs)
│   ├── credentials/
│   │   └── config.py                  # CONTEXTS_DIR + load_config (single source)
│   ├── core/
│   │   ├── api.py                     # API utilities (validate, load_df_to_postgres)
│   │   ├── sql.py                     # SQL rendering utilities
│   │   ├── validate.py                # Input validation helpers
│   │   ├── dag_services.py            # Airflow context helpers
│   │   └── backfill_services.py       # Backfill SQL helpers
│   ├── orchestrations/
│   │   ├── kmeans_training.py         # KMeans training pipeline
│   │   ├── kmeans_daily.py            # Daily cluster assignment pipeline
│   │   ├── backfill.py                # DWH backfill pipeline
│   │   ├── operation.py               # Operation pipeline
│   │   └── exchange_rate.py           # Exchange rate pipeline
│   └── ml/
│       ├── kmeans.py                  # KMeans core functions
│       └── notebooks/
│           └── kmeans_EDA.ipynb       # EDA & training exploration notebook
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
└── .github/workflows/deploy.yml       # CI/CD: auto-deploy to EC2 on push to main
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

#### RFM Feature Definitions

| Feature | Window | Description |
|---|---|---|
| **Recency** | Full period | Days since last purchase relative to `snapshot_date` |
| **Frequency** | Last 30 days | Number of orders within the 30-day window |
| **Monetary** | Last 30 days | Total revenue within the 30-day window |

Customers outside the 30-day window receive Frequency = 0, Monetary = 0 — they become the **Cooling Down** and **Dormant** segments.

#### Training (`kmeans_training_model.py`)

Trains a KMeans model on 6 months of historical RFM data and saves artifacts to DB.

| Step | Description |
|---|---|
| Extract | Raw order data: `2016-09-04 → 2017-02-28` |
| Compute RFM | Recency (full period) · Frequency & Monetary (30-day window) |
| Preprocess | `log1p(freq)` + `log1p(monetary)` + `RobustScaler` |
| Find k | Elbow + Silhouette score for k=2..7 (informational) |
| Train | `KMeans(n_clusters=3, n_init=10, max_iter=300)` |
| Label | Rank centroids by recency → assign segment names |
| Save | Artifacts · RFM clusters · training metadata · centroid metadata |

#### Daily Assign (`kmeans_daily_assign.py`)

Assigns every customer with purchase history (last 180 days) to a cluster using the pre-trained model.

| Step | Description |
|---|---|
| Extract | Raw orders: last 180 days (for recency) |
| Compute RFM | Same logic as training — recency from full lookback, F/M from 30-day window |
| Transform | `scaler.transform()` — no retraining |
| Predict | `km.predict()` → cluster assignment |
| Save | Append to `rfm_clusters_daily` with `execution_date` (idempotent) |

#### Segment Labels

| Segment | Recency | Freq 30d | Monetary 30d | MKT Strategy |
|---|---|---|---|---|
| **active_buyers** | Low (~17d) | > 0 | > 0 | Retention · Upsell · Loyalty |
| **cooling_down** | Medium (~36d) | 0 | 0 | Win-back · Limited-time offer |
| **dormant** | High (~145d) | 0 | 0 | Last-chance discount · Suppress |

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

`rfm_clusters` and `rfm_clusters_daily` columns: `customer_unique_id · recency · frequency · monetary · cluster_id · cluster_name · updated_at`

---

## Configuration

All pipeline configs live in `contexts/`. A single path constant controls where Airflow looks for them:

```python
# plugins/services/credentials/config.py
CONTEXTS_DIR = "/home/ubuntu/airflow/airflow-server/contexts"
```

Update this value when deploying to a different environment.

Example — KMeans training config:

```yaml
# contexts/kmeans_rfm_training.yaml
postgres:
  conn_id: supermarket
  training:
    schema: customer_segmentation
    table: rfm_clusters
    start_date: 2016-09-04
    end_date:   2017-02-28
    snapshot_date: 2017-02-28
    window_days: 30
    n_clusters: 3
    query: |
      SELECT c.customer_unique_id,
             DATE(o.order_purchase_timestamp) AS event_date,
             SUM(p.payment_value)             AS revenue
      FROM orders o
      JOIN customers c ON o.customer_id = c.customer_id
      JOIN order_payments p ON o.order_id = p.order_id
      WHERE o.order_status NOT IN ('canceled','unavailable')
        AND DATE(o.order_purchase_timestamp) >= '{start_date}'
        AND DATE(o.order_purchase_timestamp) <= '{end_date}'
      GROUP BY c.customer_unique_id, DATE(o.order_purchase_timestamp), o.order_id
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
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install apache-airflow scikit-learn pandas sqlalchemy psycopg2-binary pyyaml python-dotenv

# 4. Set environment variables
cp .env.example .env
# Fill in: DATABASE, USER, PASSWORD, HOST, PORT, SUPABASE_URL, SUPABASE_KEY

# 5. Run EDA notebook
jupyter notebook plugins/services/ml/notebooks/kmeans_EDA.ipynb
```

### Checking DAG import errors on EC2

```bash
airflow dags list-import-errors

# or test a specific module directly
python -c "from services.orchestrations.kmeans_training import customer_segmentation_model_training; print('OK')"
```
