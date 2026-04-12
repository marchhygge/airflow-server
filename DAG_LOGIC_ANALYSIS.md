# DAG Logic Review - centralize_pipeline

## 📊 File Overview

| File | DAG ID | Purpose | Status |
|------|--------|---------|--------|
| centralize_pipeline.py | centralize_pipeline_backfill | Main pipeline | ⚠️ |
| centralize_pipeline copy.py | centralize_pipeline_operator | Operator version | ⚠️ |
| operation_centralize_pipeline.py | operation_centralize_pipeline | Operations only | ✅ |

---

## ✅ Dependency Logic Analysis

### Current Task Dependencies:

```
centralize_pipeline.py (MAIN):
start 
  ↓
[fact_order, fact_order_item, fact_payment, fact_order_review]  ← All FACTS parallel
  ↓
dim_product, dim_order_review, dim_user  ← All DIMS after FACTS
  ↓
end

centralize_pipeline copy.py (OPERATOR):
Same structure
```

### Dependency Correctness: ✅ **LOGICALLY SOUND**

| Stage | Tasks | Why Order? |
|-------|-------|-----------|
| **Stage 1** | `fact_order`, `fact_order_item`, `fact_payment`, `fact_order_review` | Independent – load in parallel ✅ |
| **Stage 2** | `dim_product`, `dim_order_review`, `dim_user` | Depend on FACTS (filter by fact.ids) ✅ |

**Load Order Verification:**
```
dim_product: 
  - Filters by product_id IN fact_order_item ✅
  - Can start only after fact_order_item done

dim_user:
  - Filters by customer_id IN fact_order ✅
  - Filters by seller_id IN fact_order_item ✅
  - Can start only after BOTH facts done

dim_order_review:
  - Filters by order_id IN fact_order ✅
  - Can start only after fact_order done
```

**Conclusion for Stage 2**: Waiting for ALL FACTS (Stage 1) is correct and safe ✅

---

## ❌ CRITICAL ISSUE: Missing fact_order_operation

### Problem:

**`fact_order_operation` is defined in YAML but NOT in main pipelines!**

```yaml
# File exists: contexts/centralize/fact_order_operation.yaml
table: fact_order_operation
```

But:
- ❌ NOT in `centralize_pipeline.py`
- ❌ NOT in `centralize_pipeline copy.py`
- ✅ Only in `operation_centralize_pipeline.py` (separate, isolated DAG)

### Why This is Wrong:

From previous YAML review:
```sql
fact_order_operation:
  - Depends on: fact_order, fact_order_item
  - Aggregates: Total payment, items, price by order
  - Date column: order_date
```

This table is **part of the core star schema** but missing from main pipeline!

### ⚠️ Consequence:

1. If you run `centralize_pipeline_backfill`:
   - fact_order_operation is NEVER loaded
   - Separate `operation_centralize_pipeline` runs independently
   - Data inconsistency risk (different time windows, catch-up settings)

2. Two DAGs running same tables:
   - `operation_centralize_pipeline` loads fact_order_operation (Sept 3 - Dec 31)
   - `centralize_pipeline_backfill` loads other facts (April 1 onwards)
   - Separate execution dates = different replay offsets!

---

## 📋 Configuration Issues

### Issue #1: Different Start Dates

```python
# centralize_pipeline.py
start_date=datetime(2026, 4, 1)
schedule="@daily"
catchup=True

# operation_centralize_pipeline.py  
start_date=datetime(2016, 9, 3, 9, 0)
end_date=datetime(2016, 12, 31)
schedule="@daily"
catchup=True
```

**Problem**: 
- `centralize_pipeline`: Starts April 2026 → backfill from April 1 to today
- `operation_centralize_pipeline`: Fixed window Sept 3 - Dec 31, 2016 (no ongoing runs!)

**Result**: Inconsistent data load patterns, separate timing models.

### Issue #2: max_active_runs

```python
# centralize_pipeline.py
max_active_runs=1  ← Only 1 run at a time

# operation_centralize_pipeline.py
max_active_runs=3  ← Up to 3 runs parallel
```

**Problem**: Different concurrency = potential data conflicts if both write same tables.

### Issue #3: Inconsistent Dependency Syntax

```python
# centralize_pipeline.py
start >> [fact_order, fact_order_item, fact_payment, fact_order_review] 
fact_order >> [dim_product, dim_order_review, dim_user] >> end

# centralize_pipeline copy.py
start >> [fact_order, fact_order_item, fact_payment, fact_order_review] >> [dim_product, dim_order_review, dim_user] >> end
```

Both work but slightly different semantics:
- `.py`: Explicitly shows `fact_order >> dims` (clearer, but not enforced)
- ` copy.py`: All facts as group >> dims (enforces all facts before any dim)

---

## ✅ What's Correct

1. **Parallel task execution**: Facts don't depend on each other ✅
2. **Fact→Dim ordering**: Dims wait for facts ✅
3. **depends_on_past=True**: Enforces sequential execution per date ✅
4. **catchup=True**: Backfills historical dates ✅
5. **max_active_runs=1**: Prevents parallel date conflicts ✅

---

## ❌ What Needs Fixing

### Fix #1: Add fact_order_operation to main pipeline

**File**: Edit `centralize_pipeline.py`
```python
fact_order_operation = PythonOperator(
    task_id="fact_order_operation",
    python_callable=run_backfill,
    op_kwargs={**REPLAY, "config_file_name": "centralize/fact_order_operation.yaml"},
    depends_on_past=True,
)

# Add to dependency chain:
start >> [fact_order, fact_order_item, fact_payment, fact_order_review, fact_order_operation] >> ...
```

### Fix #2: Consolidate or separate clearly

**Option A (Recommended)**: Make operation_centralize_pipeline continuous
```python
# operation_centralize_pipeline.py - CHANGE TO:
start_date=datetime(2026, 4, 1)  ← Same as main
schedule="@daily"
catchup=True
max_active_runs=1  ← Same as main
```

**Option B**: Remove from main, keep separate
- Keep `operation_centralize_pipeline` isolated
- Document that it's independent
- Ensure no data race conditions

### Fix #3: Remove or rename "copy" file
- `centralize_pipeline copy.py` is duplicate
- Delete it or rename to `centralize_pipeline_operator_v1.py`

---

## 📝 Recommended Task Order

```
Stage 1: Independent FACTS (load all in parallel)
├── fact_order
├── fact_order_item  
├── fact_payment
├── fact_order_review
└── [fact_order_operation ← ADD THIS]

Stage 2: DIMs (after all FACTs)
├── dim_user (filters fact_order + fact_order_item)
├── dim_product (filters fact_order_item)
└── dim_order_review (filters fact_order)
```

---

## Scoring

| Aspect | Score | Notes |
|--------|-------|-------|
| Task ordering logic | 8/10 | Correct but missing fact_order_operation |
| Dependency chain | 9/10 | Well structured, safe wait strategy |
| Configuration | 6/10 | Duplicates, inconsistent dates |
| Code quality | 7/10 | Clear but has duplicate file |
| **Overall** | **7/10** | Fix missing table + clean up duplicates |

