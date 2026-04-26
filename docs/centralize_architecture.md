# Centralize Pipeline — Architecture

```mermaid
flowchart TD
    A[("🛒 Raw Olist Data PostgreSQL · public schema")]

    subgraph FACTS ["📦 Step 1 — Fact Tables (parallel)"]
        direction LR
        F1["fact_order Order lifecycle + totals"]
        F2["fact_order_item Item-level per order"]
        F3["fact_payment Payment transactions"]
        F4["fact_order_review Aggregated review scores"]
    end

    BARRIER["⏸️ barrier All facts must complete"]

    subgraph DIMS ["📐 Step 2 — Dimension Tables (after barrier)"]
        direction LR
        D1["dim_user Customers + Sellers"]
        D2["dim_product Product catalog"]
        D3["dim_order_review Raw review texts"]
    end

    RV["🔄 refresh_views Materialized views"]
    K[("🏛️ Data Warehouse centralize schema Supabase / PostgreSQL")]

    A --> F1 & F2 & F3 & F4
    F1 & F2 & F3 & F4 --> BARRIER
    BARRIER --> D1 & D2 & D3
    D1 & D2 & D3 --> RV
    F1 & F2 & F3 & F4 & D1 & D2 & D3 --> K
    RV --> K
```

---

## Giải thích từng bước

**Step 1 — Fact Tables (chạy song song)**
> 4 fact tables chạy cùng lúc, mỗi table load dữ liệu từ raw source theo window `[month_start, daily_end)`. Dữ liệu được filter theo `order_date` để đảm bảo chỉ insert đúng cửa sổ cần thiết.

**Barrier — tất cả facts phải xong**
> `EmptyOperator` làm điểm chờ để đảm bảo tất cả 4 fact tables đã hoàn thành trước khi dim tables bắt đầu. Dims cần join ngược lại các fact tables để lấy danh sách unique IDs.

**Step 2 — Dimension Tables (sau barrier)**
> Dim tables chạy song song sau khi barrier thông qua. Không có date column trong output — dùng EXCEPT INSERT so với toàn bộ target table để tránh duplicate.

**refresh_views — sau khi tất cả dims xong**
> Refresh tất cả materialized views được khai báo trong `report_views.yaml`. Chạy sau cùng để views luôn phản ánh dữ liệu mới nhất.

**Output — centralize schema**
> Toàn bộ dữ liệu được chuẩn hóa vào schema `centralize` trên Supabase, sẵn sàng cho BI dashboards và MCP tools.

---

## Hai DAG — Hai Orchestration Pattern

Hiện tại có 2 DAGs cho centralize pipeline, dùng logic orchestration khác nhau:

| DAG | dag_id | Orchestrator | Pattern |
|---|---|---|---|
| `star_centralize_pipeline.py` | `centralize_pipeline_operator` | `run_star_schema()` | Daily EXCEPT-based, có `barrier` + `refresh_views` |
| `centralize_pipeline.py` | `centralize_pipeline_backfill` | `run_backfill()` | Monthly loop, max_date check, dims phụ thuộc `fact_order` |

> `centralize_pipeline_operator` là pipeline chính (có `barrier`, `refresh_views`, và retroactive data support).

---

## Data Coverage & Department Access

| Table | Columns Key | Department |
|---|---|---|
| `fact_order` | order_id, customer_id, order_date, status, total_payment, total_items | Commercial |
| `fact_order_item` | order_id, product_id, seller_id, order_date, total_price, freight | Commercial |
| `fact_payment` | order_id, payment_type, installments, order_date, total_payment_value | Finance |
| `fact_order_review` | order_id, order_date, avg_score, total_reviews, last_review_date | Customer |
| `dim_user` | user_id, user_type (customer/seller), city, state | Customer |
| `dim_product` | product_id, category_name, weight, dimensions | Commercial |
| `dim_order_review` | review_id, order_id, title, message, creation_date | Customer |

> Data range: **2016-09-04 → 2018-10-17** (Brazilian e-commerce dataset)

---

## Technical Deep-Dive (for Q&A)

### Pipeline Orchestration — `centralize_pipeline_operator`

```mermaid
flowchart TD
    S([start])

    S --> FO[fact_order]
    S --> FOI[fact_order_item]
    S --> FP[fact_payment]
    S --> FOR[fact_order_review]

    FO & FOI & FP & FOR --> BAR[barrier]

    BAR --> DU[dim_user]
    BAR --> DP[dim_product]
    BAR --> DOR[dim_order_review]

    DU & DP & DOR --> RV[refresh_views]
    RV --> E([end])
```

> - Facts chạy song song từ `start` — không phụ thuộc nhau.
> - `barrier` EmptyOperator chờ tất cả 4 facts hoàn thành.
> - Dims chạy song song sau `barrier`.
> - `refresh_views` chạy cuối cùng, sau tất cả dims.
> - `depends_on_past=True` trên mỗi task → đảm bảo thứ tự thời gian, không chạy ngày T+1 khi ngày T chưa xong.

---

### Date Replay Mapping — `run_star_schema`

```mermaid
flowchart TD
    subgraph DATE ["Date Replay Mapping"]
        A1["Airflow execution_date (real: 2026-01-15)"]
        A2["offset = execution_date − real_start (2026-01-01) = 14 days"]
        A3["dataset_execution_date = 2016-09-04 + 14d = 2016-09-18"]
        A4["month_start = 2016-09-01 (first day of month)"]
        A5["daily_end = 2016-09-19 (exclusive upper bound)"]
        A1 --> A2 --> A3 --> A4 & A5
    end
```

> SQL window per run: `[month_start, daily_end)` — cửa sổ bắt đầu từ đầu tháng đến `dataset_execution_date + 1 day`. Pattern này hỗ trợ **retroactive data**: nếu một order từ đầu tháng được thêm muộn vào source, EXCEPT check sẽ phát hiện và insert vào lần chạy tiếp theo.

---

### EXCEPT-based Idempotency — `run_star_schema`

```mermaid
flowchart TD
    subgraph CHECK ["Per-run Logic"]
        B1{"Table exists?"}
        B2["CREATE TABLE AS SELECT ...\nWHERE [month_start, daily_end)"]
        B3{"EXCEPT check:\nnew rows in source vs target?"}
        B4["⏭️ Skip already in sync"]
        B5["EXCEPT INSERT:\nonly rows not in target"]
        B1 -->|No| B2
        B1 -->|Yes| B3
        B3 -->|No rows| B4
        B3 -->|Has rows| B5
    end
```

**Fact tables:** EXCEPT compares source `[month_start, daily_end)` vs target scoped to same window.

**Dim tables:** EXCEPT compares source `[month_start, daily_end)` vs entire target (no date column in dims).

> Không có monthly loop — mỗi Airflow run xử lý đúng một cửa sổ ngày.

---

### SQL Strategy per Table Type

| Table Type | First Run | Re-run / Incremental | Idempotency |
|---|---|---|---|
| **Fact** | `CREATE TABLE AS SELECT ...` | EXCEPT check → EXCEPT INSERT scoped to `[month_start, daily_end)` | Row-level EXCEPT — bỏ qua rows đã có |
| **Dim** | `CREATE TABLE AS SELECT DISTINCT ...` | EXCEPT check → EXCEPT INSERT vs entire target | Row-level EXCEPT — không duplicate |

> Fact tables dùng `order_date` range filter (`month_start` → `daily_end`) per run.
> Dim tables không có date column trong output — EXCEPT so với toàn bộ target.

---

### Source → Target Lineage

```mermaid
flowchart LR
    subgraph RAW ["public schema (raw)"]
        R1[orders]
        R2[customers]
        R3[sellers]
        R4[order_items]
        R5[order_payments]
        R6[order_reviews]
        R7[products]
    end

    subgraph DW ["centralize schema (DW)"]
        T1[fact_order]
        T2[fact_order_item]
        T3[fact_payment]
        T4[fact_order_review]
        T5[dim_user]
        T6[dim_product]
        T7[dim_order_review]
    end

    R1 & R5 & R4 --> T1
    R4 & R1       --> T2
    R5 & R1       --> T3
    R6 & R1       --> T4
    R2 & R3       --> T5
    R7            --> T6
    R6            --> T7

    T1 -.->|"IN subquery"| T5
    T2 -.->|"IN subquery"| T6
    T1 -.->|"IN subquery"| T7
```

---

### Config Structure (per table YAML)

```yaml
postgres:
  conn_id: supermarket          # Airflow connection ID → Supabase
  target:
    schema: centralize          # target schema
    table: fact_order           # target table
    date_column: order_date     # column used for EXCEPT fact window scope

query:
  function:
    create: create table if not exists {{ schema }}.{{ table }} as
    insert: insert into {{ schema }}.{{ table }}
  sql: |
    SELECT ... FROM public.orders
    WHERE order_date >= '{{start_date}}' AND order_date < '{{end_date}}'
```

---

### Module Dependency Tree

```
dags/star_centralize_pipeline.py                      ← Main pipeline (operator)
  └── services/orchestrations/operator.py              run_star_schema()
        ├── services/core/config.py                    load_config()
        ├── services/core/validate.py                  validate_config / identifier / date / pg / sql
        └── services/core/sql.py                       check_exist_table · check_data_available
                                                       render_template · execute_sql
  └── services/orchestrations/materialized_view.py     refresh_materialized_views()
        ├── services/core/config.py                    load_config()
        ├── services/core/validate.py                  validate_identifier / pg
        └── services/core/sql.py                       execute_sql

dags/centralize_pipeline.py                           ← Legacy pipeline (backfill)
  └── services/orchestrations/backfill.py              run_backfill()
        ├── services/core/config.py                    load_config()
        ├── services/core/validate.py                  validate_config / identifier / date / pg / sql
        ├── services/core/sql.py                       check_exist_table · check_data_available
        │                                              render_template · execute_sql · get_max_date
        └── services/core/backfill_services.py
              ├── resolve_raw_sql()                    CREATE vs INSERT vs EXCEPT INSERT
              ├── resolve_start_date_dt()              from max_date or config default
              └── build_sql_for_month()                render template for [start, start+1month)
```
