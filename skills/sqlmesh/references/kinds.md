# Model kinds

> SQLMesh 0.236.x.
> Verified against the 0.236.3 source (core/model/kind.py) and the official docs, 2026-10-26.

```
  VIEW                        not materialised. THE DEFAULT if kind omitted — state it anyway.
  FULL                        rebuilt from scratch every run.
  INCREMENTAL_BY_TIME_RANGE   overwrite a time window. event/fact tables.
  INCREMENTAL_BY_UNIQUE_KEY   MERGE on a key. mutable rows.
  INCREMENTAL_BY_PARTITION    overwrite the partitions present in output.
  INCREMENTAL_UNMANAGED       append-only, no interval tracking.
  SCD_TYPE_2_BY_TIME          history, driven by an updated_at column.
  SCD_TYPE_2_BY_COLUMN        history, triggered by watched columns changing.
  SCD_TYPE_2                  legacy alias of SCD_TYPE_2_BY_TIME. don't use.
  EMBEDDED                    inlined as a subquery into consumers. no table.
  SEED                        a CSV in the project.
  EXTERNAL                    tables SQLMesh reads but doesn't manage (YAML).
  MANAGED                     engine-maintained (Snowflake dynamic tables only).
  CUSTOM                      user-written Python materialization.
  DBT_CUSTOM                  internal, dbt projects only. never hand-write.
```
Syntax: `kind NAME` or `kind NAME ( p1 v1, p2 v2 )` — comma-separated, space between
name and value. Unknown/misspelt param → load error. FULL, EMBEDDED, EXTERNAL take no
`( … )` at all. Int params must be ≥1. Python models can't be VIEW/EMBEDDED/SEED/MANAGED.

---

## VIEW

`kind VIEW` · `kind VIEW ( materialized true )`. `materialized` (false): honoured on BigQuery, Databricks, Snowflake, RisingWave, StarRocks;
silently ignored elsewhere. ⚠ partitioned_by/clustered_by rejected unless materialized.

## FULL

`MODEL ( name marts.revenue_by_region, kind FULL, grain (region, month) );` No params. Re-reads all input every run. **Keeps no history**: if the source
overwrites itself, so does this model.

## INCREMENTAL_BY_TIME_RANGE

```sql
MODEL (
  name marts.orders_daily,
  kind INCREMENTAL_BY_TIME_RANGE ( time_column order_date, lookback 2 ),
  start '2025-01-01',
  cron '@daily',
  grain (order_date, region)
);

SELECT placed_at::DATE AS order_date, region::TEXT AS region, COUNT(*)::INT AS order_count
FROM staging.stg_orders
WHERE placed_at::DATE BETWEEN @start_ds AND @end_ds
GROUP BY 1, 2;
```
```
  time_column               REQUIRED. col | (col, '%Y%m%d'). must be in query output.
                            format (default '%Y-%m-%d') matters only for string columns;
                            write it in the model's dialect. docs: column should be UTC.
  lookback                  also reprocess the N preceding intervals every run (late data).
  batch_size                max intervals per backfill task. default: all in one.
  batch_concurrency         max parallel batches. default: connection concurrent_tasks.
  partition_by_time_column  default true → time_column auto-prepended to partitioned_by.
  auto_restatement_intervals  last N intervals for auto_restatement_cron. omit → all.
  forward_only · disable_restatement (default false) · auto_restatement_cron · on_*_change
  ⚠ your WHERE filters the INPUT. SQLMesh ALSO filters the OUTPUT on time_column
    BETWEEN start/end and overwrites exactly that range in the target: output rows
    outside the window are dropped; target rows in it that the query no longer
    returns are deleted.
  ⚠ no input WHERE → still valid and correct, but scans all input every run.
  ⚠ macro must match column type: DATE → @start_ds/@end_ds,
    TIMESTAMP → @start_dt/@end_dt (or _ts / _tstz).
  ⚠ self-referencing query → batch_concurrency forced to 1.
  ⚠ the only kind whose restatement is partial (per interval).
```

## INCREMENTAL_BY_UNIQUE_KEY

```sql
MODEL (
  name marts.customer_state,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key customer_id,
    when_matched (
      WHEN MATCHED AND source.is_deleted THEN DELETE
      WHEN MATCHED THEN UPDATE SET target.status = source.status
    ),
    merge_filter source.updated_at > @start_ds
  ),
  grain customer_id
);
```
```
  unique_key         REQUIRED. col | (col, col) | [col, col] | expression
  when_matched       default: update all columns. source./target. aliases REQUIRED.
                     several WHEN MATCHED allowed (Redshift: one, UPDATE/DELETE only).
  merge_filter       predicate ANDed into MERGE ON (prunes target scan). macros OK.
  batch_size         max intervals per task (needs a time filter in the query).
  batch_concurrency  must be 1 (or omitted). anything else → validation error.
  lookback           reprocess N preceding intervals.
  forward_only · disable_restatement (default false) · auto_restatement_cron · on_*_change
  ⚠ duplicate keys in output: NOT detected or deduped. first load inserts them all;
    native MERGE errors or picks arbitrarily (engine-dependent); logical merge keeps
    one arbitrary row. dedupe in the query + add a unique_values audit.
  ⚠ no time filter in the query → every run reads the whole source.
  ⚠ restatement rebuilds the WHOLE table from the query; lost if source lacks history.
  ⚠ native MERGE: BigQuery, Snowflake, Databricks, MSSQL, Fabric, Postgres ≥15;
    Spark/Trino/Athena only on table formats with MERGE (Delta/Iceberg);
    Redshift only with connection `enable_merge true`.
    Others (DuckDB, MySQL, ClickHouse, StarRocks, Postgres <15, Redshift default)
    use delete+insert: when_matched / merge_filter there → runtime ERROR.
```

## INCREMENTAL_BY_PARTITION

```
  MODEL ( name marts.events_by_region, kind INCREMENTAL_BY_PARTITION, partitioned_by region );
  partitioned_by (model-level) REQUIRED. disable_restatement (false) · auto_restatement_cron · on_*_change
  ⚠ always forward-only; writing `forward_only` in the kind → load error.
  ⚠ each run replaces every partition present in output; others untouched. no
    intervals, no batch_size/lookback — the query decides what reloads.
  ⚠ restatement rebuilds the WHOLE table. non-idempotent: data-loss risk. any engine.
```

## INCREMENTAL_UNMANAGED

```
  MODEL ( name marts.event_log, kind INCREMENTAL_UNMANAGED );
  insert_overwrite     default false. true → overwrite partitions present in output
                       instead of appending; requires model-level partitioned_by.
  forward_only (true) · disable_restatement (TRUE; if false, restate = full rebuild)
  auto_restatement_cron · on_*_change
  ⚠ appends output each run. no intervals. batch_size/batch_concurrency/lookback →
    load error. duplicates are your problem — filter in the query.
```

## SCD_TYPE_2_BY_TIME / SCD_TYPE_2_BY_COLUMN

```sql
MODEL ( name marts.cust_hist, kind SCD_TYPE_2_BY_TIME ( unique_key customer_id, updated_at_name updated_at ) );
MODEL ( name marts.cust_hist, kind SCD_TYPE_2_BY_COLUMN ( unique_key customer_id, columns [plan_id, status] ) );
```
```
  shared  unique_key REQUIRED (col | (col, col) | [col, col])
          valid_from_name (valid_from) · valid_to_name (valid_to)
          invalidate_hard_deletes (false) · time_data_type (TIMESTAMP; DATETIME on BQ)
          batch_size (none) · forward_only (true) · disable_restatement (TRUE)
          auto_restatement_cron · on_*_change
  by_time updated_at_name (updated_at; must be in output) · updated_at_as_valid_from (false)
  by_col  columns REQUIRED ([a, b] | (a, b) | [*] | * — * = all columns)
          execution_time_as_valid_from (false)
          updated_at_name (optional: use this column instead of execution time)
  adds valid_from (inclusive) · valid_to (exclusive, NULL = current row)
  ⚠ restatement DISABLED by default; if enabled it rebuilds from the current source
    → history destroyed. History exists only from the first run; never recoverable.
  ⚠ valid_from of a NEW key:
      BY_TIME  1970-01-01 00:00:00 always (every new key, not just first load);
               updated_at_as_valid_from true → its updated_at.
      BY_COL   1970-01-01 on first load only, execution time afterwards;
               execution_time_as_valid_from true → execution time always.
  ⚠ invalidate_hard_deletes false: key gone from source stays current (valid_to NULL).
    true: closed at execution time → query MUST return the full current source;
    a filtered/incremental query closes every key it omits.
  ⚠ query output must be unique on unique_key.
  ⚠ every run rewrites the entire table — cost grows with history. no lookback.
```

## EMBEDDED

`MODEL ( name staging.active_customers, kind EMBEDDED );` No params. Inlined as a subquery into every consumer; no table. ⚠ `audits` → load error.

## SEED

```sql
MODEL (
  name staging.country_codes,
  kind SEED ( path '../seeds/country_codes.csv', csv_settings ( delimiter = ';' ) ),
  columns ( code TEXT, name TEXT )
);
```
```
  path          REQUIRED. relative to the model file; '$root/…' = project root.
  batch_size    CSV rows per insert batch. default 1000.
  csv_settings  ( k = v, … ): delimiter, quotechar, doublequote, escapechar,
                skipinitialspace, lineterminator, encoding, na_values, keep_default_na
  ⚠ no query. declare columns (order overrides CSV header) or types are inferred.
  ⚠ reloaded only when the CSV or model changes; restatement is skipped.
```

## EXTERNAL

Not a .sql model: `external_models.yaml` (name + columns) — schema of tables SQLMesh
reads but doesn't own. No params.

## MANAGED

`MODEL ( name m.live, kind MANAGED, physical_properties ( target_lag = '20 minutes' ) );`
No params. Snowflake only (dynamic table); `target_lag` physical property REQUIRED.
Engine refreshes it, `sqlmesh run` never does. Restatement off. Docs: unstable — avoid.

## CUSTOM

```
  MODEL ( name m.x, kind CUSTOM ( materialization 'my_mat', materialization_properties ( k = 'v' ) ) );
  materialization             REQUIRED. NAME of a CustomMaterialization subclass in
                              materializations/*.py or a `sqlmesh.materializations`
                              entry point. not found → load error.
  materialization_properties  ( k = v, … ) passed to the class.
  forward_only · disable_restatement (false) · batch_size · batch_concurrency · lookback
  auto_restatement_cron · auto_restatement_intervals
  ⚠ on_destructive_change / on_additive_change NOT accepted → load error.
```

---

## Shared kind params

```
  forward_only            changes never rebuild history          → plans-envs.md
  disable_restatement     block restating this model (plan warns and skips it)
  on_destructive_change   error (default) | warn | allow | ignore   (case-insensitive)
  on_additive_change      allow (default) | warn | error | ignore
                          both act only on forward-only changes (forward_only model or
                          forward-only plan); checked at plan AND run time.
                          project-wide default via model_defaults.
  auto_restatement_cron   cron: restate the model (+ downstream) on that schedule.
                          only in `sqlmesh run` on prod. no-op while disable_restatement
                          is true (so SCD/UNMANAGED need it false). docs: prefer lookback.

  accepted by          ITR  UK   PART  UNMAN  SCD  CUSTOM
  on_*_change           ✓    ✓    ✓     ✓      ✓    ✗
  auto_restat_cron      ✓    ✓    ✓     ✓      ✓    ✓
  auto_restat_intervals ✓    ✗    ✗     ✗      ✗    ✓
  batch_size            ✓    ✓    ✗     ✗      ✓    ✓
  batch_concurrency     ✓    =1   ✗     ✗      ✗    ✓
  lookback              ✓    ✓    ✗     ✗      ✗    ✓
  forward_only          f    f    ✗(T)  T      T    f      f/T = default false/true
  disable_restatement   f    f    f     T      T    f
  VIEW/FULL/SEED/EMBEDDED/EXTERNAL/MANAGED accept none of these.
  Restating any kind except INCREMENTAL_BY_TIME_RANGE rebuilds the whole table.
```
