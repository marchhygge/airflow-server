# KMeans RFM Customer Segmentation — High-Level Architecture

```mermaid
flowchart TD
    A[("🛒 E-commerce Transaction Data")]

    subgraph TRAIN ["📚 Phase 1 — Model Training (Once)"]
        direction TB
        B["Calculate RFM Score per Customer"]
        C["Machine Learning KMeans Clustering"]
        D[("💾 Saved Model & Parameters")]
    end

    subgraph DAILY ["🔄 Phase 2 — Daily Assignment"]
        direction TB
        E["New Daily Transactions"]
        F["Apply Saved Model (no retraining)"]
    end

    subgraph SEGMENTS ["🎯 Customer Segments"]
        direction LR
        G["🟢 Active Buyers 35% — recent, frequent"]
        H["💎 High Value 28% — recent, high spend"]
        I["🟡 Cooling Down 26% — dropping off"]
        J["🔴 Dormant 11% — inactive"]
    end

    K[["📊 Dashboard & Analytics"]]

    A --> B
    B --> C
    C --> D
    D --> F
    E --> F
    F --> G & H & I & J
    G & H & I & J --> K
```

---

## Giải thích từng phase

**Phase 1 — Training (chạy một lần)**
> Hệ thống học từ lịch sử giao dịch: mỗi khách hàng được chấm điểm theo 3 tiêu chí — mua gần đây chưa, mua bao nhiêu lần, chi bao nhiêu tiền. Sau đó thuật toán KMeans tự động chia khách hàng thành 4 nhóm và lưu lại mô hình.

**Phase 2 — Daily (chạy mỗi ngày)**
> Mỗi ngày, hệ thống dùng mô hình đã học để phân loại khách hàng mới vào đúng nhóm — không cần train lại.

**4 Segments (output thực tế)**

| Segment | % Users | Đặc điểm | Chiến lược |
|---|---|---|---|
| 🟢 Active Buyers | 35% | Mua gần đây, thường xuyên | Retention · Cross-sell · Loyalty |
| 💎 High Value | 28% | Mua gần đây, chi tiêu cao | VIP perks · Upsell · Exclusive offers |
| 🟡 Cooling Down | 26% | Đang giảm tần suất | Win-back · Limited-time offer |
| 🔴 Dormant | 11% | Không hoạt động | Last-chance discount · Suppress |

---

## Technical Deep-Dive (for Q&A)

### Pipeline Orchestration (Apache Airflow)

```mermaid
flowchart LR
    subgraph DAG1 ["DAG 1 — kmeans_training_model"]
        direction LR
        t0([start]) --> t1[train_kmeans_model] --> t2([end])
    end

    subgraph DAG2 ["DAG 2 — kmeans_daily_assign_pipeline"]
        direction LR
        d0([start]) --> d1[daily_assign_clusters] --> d2([end])
    end

    DAG1 -->|"artifacts saved to DB"| DAG2
```

> - DAG 1 chạy một lần trên dữ liệu training (2016-09-04 → 2017-02-28), `depends_on_past=True` đảm bảo tuần tự.
> - DAG 2 chạy mỗi ngày từ 2026-04-01, `catchup=True` để backfill toàn bộ lịch sử. Hai DAG liên kết qua DB, không coupling trực tiếp.

---

### Training Pipeline — Step by Step

```mermaid
flowchart TD
    A[("PostgreSQL orders · customers order_payments")]
    
    A -->|"SQL JOIN filter: 2016-09-04 → 2017-02-28"| B

    subgraph FEAT ["Feature Engineering"]
        B["Raw orders customer_unique_id · event_date · revenue"]
        B --> C["Compute RFM per customer"]
        C --> C1["Recency = days since last order (full period → snapshot 2017-02-28)"]
        C --> C2["Frequency = # orders in last 60d"]
        C --> C3["Monetary = Σ revenue in last 60d"]
    end

    subgraph PREP ["Preprocessing"]
        D["log1p transform freq & monetary (reduce right skew)"]
        E["RobustScaler median + IQR normalization (robust to outliers)"]
        C1 & C2 & C3 --> D --> E
    end

    subgraph MODEL ["Model Training"]
        F["KMeans n_clusters=4 n_init=10, max_iter=300"]
        G["Label Clusters by centroid rank recency ↑ → dormant monetary ↑ → high_value"]
        E --> F --> G
    end

    subgraph STORE ["Persist Artifacts"]
        H[("ml_artifacts pickle KMeans + Scaler upsert on conflict")]
        I[("rfm_clusters assignments snapshot replace")]
        J[("kmeans_training_log inertia · silhouette · n_iter scaler medians/IQRs")]
        K[("kmeans_centroid_log centroid coords scaled + original scale")]
        G --> H & I & J & K
    end
```

---

### Daily Inference Pipeline — Step by Step

```mermaid
flowchart TD
    subgraph DATE ["Date Replay Mapping"]
        A1["Airflow execution_date (real: 2026-04-15)"]
        A2["offset = real_date − 2026-04-01 = +14 days"]
        A3["snapshot_date = 2017-03-01 + 14d = 2017-03-15"]
        A1 --> A2 --> A3
    end

    subgraph LOAD ["Load Artifacts"]
        B["SELECT artifact_data FROM ml_artifacts WHERE artifact_name = 'scaler' / 'kmeans_model'"]
        C["pickle.loads → RobustScaler + KMeans"]
        B --> C
    end

    subgraph INFER ["Inference (no retraining)"]
        D["Extract orders 180-day lookback for recency distribution"]
        E["Compute RFM same logic as training"]
        F["log1p → scaler.transform → km.predict"]
        D --> E --> F
    end

    subgraph SAVE ["Save Results"]
        G["DELETE WHERE execution_date = snapshot (idempotent rerun)"]
        H[("rfm_clusters_daily append customer · cluster · execution_date")]
        G --> H
    end

    A3 --> D
    C --> F
    F --> G
```

---

### RFM Feature Definition

| Feature | Window | Formula | Why |
|---|---|---|---|
| **Recency** | Full period | `snapshot_date − max(order_date)` in days | Đo mức độ active gần nhất |
| **Frequency** | Last **60 days** | Count of orders in window | Đo tần suất mua trong thời gian gần |
| **Monetary** | Last **60 days** | `Σ payment_value` in window | Đo giá trị chi tiêu gần đây |

> Customers mua ngoài 60-day window → Frequency = 0, Monetary = 0 → tự động rơi vào **Cooling Down** hoặc **Dormant**.

---

### Cluster Labeling Logic

```
centroids (original scale)
        │
        ├─ highest Recency  ──────────────────► dormant
        │
        └─ remaining 3
                │
                ├─ highest Monetary  ─────────► high_value
                │
                └─ remaining 2
                        │
                        ├─ lowest Recency  ───► active_buyers
                        └─ other  ────────────► cooling_down
```

> Logic này đảm bảo label assignment **deterministic** và không phụ thuộc vào cluster ID ngẫu nhiên của KMeans mỗi lần train.

---

### Database Schema (customer_segmentation)

```mermaid
erDiagram
    ml_artifacts {
        varchar artifact_name PK
        bytea   artifact_data
        timestamp updated_at
    }

    rfm_clusters {
        varchar customer_unique_id PK
        int     recency
        float   frequency
        float   monetary
        int     cluster_id
        varchar cluster_name
        timestamp updated_at
    }

    rfm_clusters_daily {
        varchar customer_unique_id
        int     recency
        float   frequency
        float   monetary
        int     cluster_id
        varchar cluster_name
        date    execution_date
        timestamp updated_at
    }

    kmeans_training_log {
        serial  id PK
        timestamp trained_at
        date    start_date
        date    end_date
        int     n_samples
        int     n_clusters
        float   inertia
        float   silhouette
        int     n_iter
        float   recency_median
        float   frequency_median
        float   monetary_median
        float   recency_iqr
        float   frequency_iqr
        float   monetary_iqr
    }

    kmeans_centroid_log {
        serial  id PK
        int     training_id FK
        int     cluster_id
        varchar cluster_name
        float   recency_scaled
        float   frequency_scaled
        float   monetary_scaled
        float   recency_orig
        float   frequency_orig
        float   monetary_orig
    }

    kmeans_training_log ||--o{ kmeans_centroid_log : "training_id"
```
