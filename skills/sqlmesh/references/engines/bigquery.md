# BigQuery

> Read when `list_tables` reports `dialect: bigquery`. Write in BigQuery SQL.
> Verified against the SQLMesh 0.236.3 BigQuery adapter and sqlglot, 2026-10-28.
> Live BigQuery behaviour not yet tested here — validate is the final check.

## SQLMesh on BigQuery

```
  names           project.dataset.table   catalog = PROJECT, schema = DATASET
                  model name = dataset.model; SQLMesh adds the project
  quoting         backticks: `my-project.dataset.table` (hyphens need them)
  transactions    none — a failed plan can leave partial tables
  MERGE           native. INCREMENTAL_BY_UNIQUE_KEY and insert-overwrite use MERGE
  partitioned_by  supported: a DATE/TIMESTAMP column, or DATE_TRUNC / TIMESTAMP_TRUNC
                  on one. INCREMENTAL_BY_TIME_RANGE partitions by time_column
  clustered_by    supported, up to 4 columns
  VIEW materialized true   supported (materialized view)
  comments        table + column comments registered, max 1024 chars
  SCD time_data_type       becomes DATETIME
```

## Types

```
  INT64 · FLOAT64 · NUMERIC · BIGNUMERIC · BOOL · STRING · BYTES
  DATE · DATETIME (no tz) · TIMESTAMP (UTC) · TIME · JSON
  STRUCT<a INT64, b STRING> · ARRAY<STRING>
```

`x::TEXT` is accepted and becomes `CAST(x AS STRING)`. Prefer native names
(`::INT64`, `::STRING`, `::FLOAT64`) so the model reads as BigQuery.

## Nested fields (STRUCT)

`describe_table` lists nested paths: `data.sys.supervisor.latency_ms INT64`.

```sql
SELECT
  data.sys.supervisor.latency_ms::INT64   AS latency_ms,
  data.sys.supervisor.bot_name::STRING    AS bot_name
FROM raw.events
```

```
  ⚠ alias every nested path — the output column name must be inferrable
  ⚠ ARRAY of STRUCT: UNNEST first —
      FROM raw.events, UNNEST(data.items) AS item   then item.price
  ⚠ JSON columns are not STRUCTs: JSON_VALUE(data, '$.sys.bot_name') returns STRING
```

## Percentiles and metric shorthand

A metric definition like `p95(latency_ms)` is shorthand, not a function.

```
  p50 / p95 / p99        APPROX_QUANTILES(x, 100)[OFFSET(95)]        ← aggregate
                         PERCENTILE_CONT(x, 0.95) OVER (PARTITION BY …)  ← window only
  max / min / avg / sum  MAX(x) · MIN(x) · AVG(x) · SUM(x)
  count                  COUNT(*) · COUNTIF(cond) for filtered counts
```

```
  ⚠ PERCENTILE_CONT is a WINDOW function in BigQuery — it cannot be used with
    GROUP BY. For a grouped percentile use APPROX_QUANTILES
  ⚠ APPROX_QUANTILES is approximate — say so when it matters
```

Translate a definition's `filter` into `WHERE` (or `COUNTIF` / `IF` inside the
aggregate when one model computes several filtered metrics):

```sql
SELECT
  session_id::STRING AS session_id,
  APPROX_QUANTILES(IF(response_status IN ('success','oos'), latency_ms, NULL), 100)[OFFSET(95)]
    AS p95_successful_latency_ms,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS p95_overall_latency_ms
FROM …
WHERE event_type = 'bot_response_received' AND bot_name = 'haio_dummy_bot'
GROUP BY 1
```

`APPROX_QUANTILES` ignores NULLs, so `IF(cond, x, NULL)` filters per metric.

## Dates and times

```
  DATE_TRUNC(d, MONTH)          on DATE         ← argument order: value, part
  TIMESTAMP_TRUNC(ts, DAY)      on TIMESTAMP
  DATE_DIFF(a, b, DAY)          a − b in days   ← value, value, part
  DATE_ADD(d, INTERVAL 1 DAY)   · TIMESTAMP_ADD(ts, INTERVAL 1 HOUR)
  DATE(ts)                      TIMESTAMP → DATE
  CURRENT_DATE() · CURRENT_TIMESTAMP()
```

```
  ⚠ Postgres-style DATE_TRUNC('month', d) is transpiled to TIMESTAMP_TRUNC — returns
    TIMESTAMP, not DATE. Write the BigQuery form directly
  ⚠ time macros: DATE column → @start_ds/@end_ds ; TIMESTAMP → @start_ts/@end_ts
    or @start_dt/@end_dt
```

## SQL traps that pass the dry run

```
  division        a / b returns FLOAT64 (no truncation) but ERRORS on zero at run
                  time → SAFE_DIVIDE(a, b)
  casts           CAST('abc' AS INT64) errors at run time → SAFE_CAST
  NULL compare    x != 'a' drops NULL rows → IS DISTINCT FROM
  NOT IN          one NULL in the list/subquery → zero rows → NOT EXISTS
  string concat   CONCAT(a, b) is NULL if any arg is NULL → COALESCE first
  case            string comparison is case-sensitive → LOWER(x) = 'value'
  GROUP BY        ordinals (GROUP BY 1, 2) are allowed
  QUALIFY         filter on window functions: QUALIFY ROW_NUMBER() OVER (…) = 1
```

## Cost

Queries bill by bytes scanned. SELECT only the columns you need, and filter on the
partition column in incremental models so each run reads one partition.

## What validate's explain step does here

BigQuery has no EXPLAIN — the step runs a **dry-run job**. It checks syntax,
tables, columns, types and functions and reports bytes that would be scanned.
It runs nothing and reads no data. It does not catch runtime errors (divide by
zero, bad casts of real values) or wrong results.
