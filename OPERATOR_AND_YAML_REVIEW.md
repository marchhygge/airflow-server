# Operator.py & YAML Files Logic Review

## 1. OPERATOR.PY - OVERVIEW & LOGIC ANALYSIS

### ✅ Overall Logic: SOUND

The `run_star_schema()` operator implements a well-designed **incremental, retroactive-aware star schema loader**.

#### Key Algorithm Concepts:

```
Date Mapping (Replay Logic):
├── A = real_start         → When DAG first runs in production
├── B = dataset_start      → First date of source dataset (e.g., 2016-09-04)
├── C = execution_date     → Airflow execution date (from context)
├── offset                 → C - A (in days)
└── dataset_execution_date → B + offset (applies offset to dataset timeline)

SQL Window:
├── month_start = First day of month(dataset_execution_date)
└── daily_end   = dataset_execution_date + 1 day (exclusive upper bound)
```

#### Processing Logic per DAG Run:

| Scenario | Action |
|----------|--------|
| Table NOT exist | `CREATE TABLE AS SELECT` (load full month) |
| Table EXISTS + New rows in window | `EXCEPT INSERT` (insert missing rows) |
| Table EXISTS + No changes | Skip (no-op) |

#### Dimension vs Fact Table Handling:

**Dimension Tables (prefix: `dim_*`)**
```
Source Comparison: SELECT * FROM ({source_sql}) EXCEPT SELECT * FROM {schema}.{table}
- No date filtering on target (entire table compared)
- Reason: Dims are slowly-changing reference data (small volume)
```

**Fact Tables (prefix: `fact_*`)**
```
Source Comparison: SELECT * FROM ({source_sql}) EXCEPT SELECT * FROM {schema}.{table} 
                   WHERE {date_column} >= '{month_start}' AND {date_column} < '{daily_end}'
- Scoped date filter on target (only compare month-to-date window)
- Reason: Facts are large, incremental (only month's data relevant)
```

#### ✅ Strengths:
1. **Retroactive data handling**: If order from earlier in month arrives late, EXCEPT detects it
2. **Incremental loading**: Only processes new/changed rows
3. **Date replay**: Offset-based time travel allows backfill/replay scenarios
4. **Monthly windowing**: Prevents redundant re-processing of old data (for facts)
5. **Clear logging**: Excellent debugging information

#### ⚠️ Minor Issues:

**Issue #1: Fragile dim detection**
```python
is_dim = table.lower().startswith("dim")  # Currently line ~100
```
- ✓ Works but naming convention-dependent
- Consider: Make `is_dim` explicit in YAML config instead

**Issue #2: Unused `based_on` field in DIM configs**
```yaml
# In dim_*.yaml files:
based_on: fact_order  # Defined but never used in operator.py
```
- Field is semantic documentation but not enforced
- Could be used to validate load order

---

## 2. YAML FILES - FACT vs DIM CLASSIFICATION

### ❌ CRITICAL ISSUE: `dim_order_review` Misclassification

#### Current State:
```yaml
# File: contexts/centralize/dim_order_review.yaml
table: dim_order_review
sql: |
  select distinct ors.review_id, ors.order_id, ors.review_comment_title, 
                  ors.review_comment_message, ors.review_creation_date, 
                  ors.review_answer_timestamp
  from public.order_reviews ors
  where ors.order_id in (select distinct fo.order_id from centralize.fact_order fo)
```

#### ❌ Problems:

1. **Not a Reference Dimension**: 
   - Contains transactional data (review text, timestamps)
   - Review ID is primary key, not dimensional attribute
   - Should be a **FACT table**, not DIM

2. **Naming Conflicts**:
   - Already have `fact_order_review` (aggregated reviews)
   - `dim_order_review` duplicates data differently
   - Confusing for analytics consumers

3. **Incorrect SQL Window Usage**:
   - Filters by `fact_order.order_id` but outputs review columns
   - For true DIM: should output stable attributes (rarely changes)
   - For true FACT: should aggregate by order_date

4. **Dependency Issue**:
   - Requires `fact_order` to load first
   - But DIM should be independent or load before FACTS

#### ✅ Recommendation:
**REMOVE `dim_order_review` OR convert to `fact_order_review_detail`**

---

### ✅ Correct Dimension Tables (3/3):

#### 1. dim_user
```yaml
├── Type: ✅ DIMENSION (correct)
├── Content: Customer & Seller attributes
├── Key Columns: user_id, user_type, city, state
├── Grain: One row per (user_id, user_type)
└── Analysis: Good. Combines customer + seller into unified dim_user
```

#### 2. dim_product
```yaml
├── Type: ✅ DIMENSION (correct)
├── Content: Product attributes (physical dimensions, category)
├── Key Columns: product_id, category_name, dimensions
├── Grain: One row per product_id
└── Analysis: Good. Static attributes, slow-changing
```

#### 3. dim_order_review (PROBLEMATIC - see above)
```yaml
├── Type: ❌ SHOULD BE FACT (currently DIM)
├── Content: Review comments, timestamps, review_id
├── Grain: One row per review_id (NOT per order)
└── Issue: Transactional data, not dimensional/reference
```

---

### ✅ Correct Fact Tables (5/5):

#### 1. fact_order ⭐ CORE FACT
```yaml
├── Type: ✅ FACT (correct)
├── Grain: One row per order_id
├── Measures: total_payment, total_items, total_price
├── Dimensions: customer_id (explicit), order_status
├── Date: order_date (order_purchase_timestamp)
└── Analysis: Excellent. Main transaction fact table
```

#### 2. fact_order_item
```yaml
├── Type: ✅ FACT (correct)
├── Grain: One row per (order_id, order_item_id, product_id, seller_id)
├── Measures: total_price, total_freight_value
├── Dimensions: product_id, seller_id (foreign keys)
├── Date: order_date
└── Analysis: Good. Item-level fact for drill-down analysis
```

#### 3. fact_order_operation
```yaml
├── Type: ✅ FACT (correct)
├── Grain: One row per order_id
├── Measures: total_payment, total_items, total_price, order_status
├── Dimensions: customer_id, order_status
├── Date: order_date
└── Analysis: Operational view of orders (combines order + payment + items)
```

#### 4. fact_order_review
```yaml
├── Type: ✅ FACT (correct)
├── Grain: One row per order_id (aggregated)
├── Measures: avg_score, total_reviews, last_review_date
├── Date: order_date
└── Analysis: Good. Aggregated review metrics per order
```

#### 5. fact_payment
```yaml
├── Type: ✅ FACT (correct)
├── Grain: One row per (order_id, payment_type, payment_sequential)
├── Measures: total_payment_value
├── Dimensions: payment_type, payment_installments
├── Date: order_date
└── Analysis: Good. Payment breakdown per order
```

---

## 3. DEPENDENCY ANALYSIS

### Load Order (Current):
```
Blocking Dependencies:
├── fact_order (independent)
├── fact_order_item (independent)
├── fact_order_operation (depends: fact_order, fact_order_item)
├── fact_payment (independent)
├── fact_order_review (independent)
├── dim_user (depends: fact_order, fact_order_item) ⚠️
├── dim_product (depends: fact_order_item) ⚠️
└── dim_order_review (depends: fact_order) ⚠️

Logic: All DIM tables depend on FACT tables (filter by fact table IDs)
This is INTENTIONAL for slowly-changing dim approach (load from facts)
```

### ✅ Dependency Logic is CORRECT:
- Dims filter by fact_order.order_id, fact_order_item.product_id, etc.
- This pattern is valid: "Derive dims from facts to ensure consistency"
- Typical in data warehouses using this approach

---

## 4. YAML DATE COLUMN INCONSISTENCIES

### ⚠️ Date Column Usage in DIM Tables:

```yaml
# All DIM tables use:
date_column: order_date
start_date: 2016-09-04
end_date: 2018-10-17
```

**Issue**: `order_date` is NOT in the output of these DIM tables.

```yaml
dim_user:
  Output columns: user_type, user_id, user_unique_id, city, state
  Has order_date? NO ❌
  
dim_product:
  Output columns: product_id, category_name, weight_g, length_cm, ...
  Has order_date? NO ❌
  
dim_order_review:
  Output columns: review_id, order_id, review_comment_*
  Has order_date? NO ❌
```

**Root Cause**: `date_column` is used for **backfill logic** (finding max date), not output.
- Operator extracts `date_column` value from `/target/` config
- Uses it to scope EXCEPT comparisons for backfill
- For DIM tables: backfill logic ignores date scope anyway (compares entire table)

**Recommendation**: Add clarifying comment in dim YAMLs:
```yaml
date_column: order_date  # For backfill logic; NOT included in output
```

---

## 5. CONFIGURATION BEST PRACTICES ADHERENCE

| Aspect | Status | Details |
|--------|--------|---------|
| SQL syntax validation | ✅ | Operator validates SQL template |
| Connection ID validation | ✅ | Validates conn_id = "supermarket" |
| Schema/Table name validation | ✅ | Validates identifiers |
| Date logic validation | ✅ | Validates date ranges |
| Non-null requirements | ✅ | All required fields present |
| Template placeholder syntax | ✅ | Uses `{{ schema }}`, `{{ table }}` |

---

## SUMMARY OF FINDINGS

### ✅ What's Working Well:
1. **Operator logic**: Sound, handles retroactive data correctly
2. **Star schema design**: 5 proper fact tables + 2 proper dimensions
3. **Incremental loading**: EXCEPT-based approach prevents duplicates
4. **Date handling**: Month-based windowing + offset replay mechanism
5. **SQL quality**: CTEs clear, aggregations correct, joins well-organized

### ❌ What Needs Fixing:
1. **dim_order_review**: Misclassified (should be FACT, not DIM)
   - Contains transactional review details, not dimensional attributes
   - Action: Consider converting to `fact_order_review_detail` or removing duplicate

### ⚠️ Recommendations:
1. Make `is_dim` detection explicit in YAML (add `type: fact|dim` field) instead of naming-based
2. Document that `date_column` in DIM configs is for **backfill logic only**, not output
3. Add validation that all FACT tables have `date_column` with matching `{{start_date}}, {{end_date}}`
4. Consider adding `priority` field to enforce load order (currently implicit)
5. Test retroactive data scenario: Insert order from month 1 on day 31 to verify EXCEPT catch it

---

## Code Quality Score: 8/10

**Strengths**: Clean architecture, good separation of concerns, excellent logging
**Improvements needed**: dim_order_review classification, make dim detection configurable
