# Audits

> SQLMesh 0.236.x
> Verified against the 0.236.3 source (core/audit/builtin.py, core/audit/definition.py,
> core/model/definition.py) and the official docs, 2026-10-26.

An audit is a query that returns **bad rows**. Zero rows = pass. It runs after the
model's data is written, during `plan` (backfill) and `run`.
**This agent cannot run audits** — they run when a person plans or runs.

```
  blocking (default)   failure raises; the plan/run stops for that model
  non-blocking         failure is logged as a warning; execution continues
```

## Attaching

```sql
MODEL (
  name marts.orders_daily,
  kind FULL,
  grain (order_date, region),
  audits (
    unique_combination_of_columns(columns := (order_date, region)),
    not_null(columns := (order_date, region)),
    accepted_range(column := conversion_rate, min_v := 0, max_v := 1),
    number_of_rows(threshold := 0)
  )
);
```

Arguments use `:=`. A bare name with no args is allowed: `audits (my_custom_audit)`.

```
  non-blocking   append _non_blocking to any built-in:  not_null_non_blocking(columns := (id))
                 or at the use site:                    not_null(columns := (id), blocking := false)
  condition      EVERY built-in except valid_http_method accepts condition := <expr>
                 → audit only rows matching it:  not_null(columns := (x), condition := status = 'paid')
```

## Built-ins — complete list for 0.236.3

```
  audit                          required args                       optional (default)
  ─────────────────────────────  ──────────────────────────────────  ──────────────────────────
  not_null                       columns := (a, b)
  unique_values                  columns := (a, b)  each unique alone
  unique_combination_of_columns  columns := (a, b)  unique together
  accepted_values                column :=, is_in := (...)
  not_accepted_values            column :=, is_in := (...)
  accepted_range                 column :=  + min_v and/or max_v     inclusive (true)
  number_of_rows                 threshold :=                        fails if rows <= threshold
  forall                         criteria := (expr, expr, ...)       fails rows where any is false
  at_least_one                   column :=                           fails if ALL values NULL
  not_constant                   column :=                           fails if ≤ 1 distinct value
  not_empty_string               column :=
  not_null_proportion            column :=, threshold :=             fails if non-null ≤ threshold
  sequential_values              column :=                           interval (1)
  mutually_exclusive_ranges      lower_bound_column :=,              partition_clause
                                 upper_bound_column :=                 (PARTITION BY ...)
  valid_uuid                     column :=
  valid_email                    column :=
  valid_url                      column :=                           http/https/ftp only
  valid_http_method              column :=                           (no condition arg)
  match_regex_pattern_list       column :=, patterns := ('re', ...)  fails if matches NONE
  not_match_regex_pattern_list   column :=, patterns := ('re', ...)  fails if matches ANY
  match_like_pattern_list        column :=, patterns := ('%x%', ...) fails if matches NONE
  not_match_like_pattern_list    column :=, patterns := ('%x%', ...) fails if matches ANY
  string_length_equal            column :=, v :=
  string_length_between          column :=  + min_v and/or max_v     inclusive (true)
  mean_in_range                  column :=  + min_v and/or max_v     inclusive (true)
  stddev_in_range                column :=  + min_v and/or max_v     inclusive (true)
  z_score                        column :=, threshold :=             fails rows |z| > threshold
  kl_divergence                  source_column :=, target_column :=,
                                 threshold :=
  chi_square                     column_a :=, column_b :=,           dependent (true)
                                 critical_value :=
```

Not in 0.236.3 (commented out in source — **don't emit**): `relationship`, `equality`,
`cardinality_equality`, `equal_row_count`, `fewer_rows_than`. Cross-model checks need a
custom or standalone audit.

```
  ⚠ plural columns := for not_null / unique_values / unique_combination_of_columns.
    everything else is singular column := — except kl_divergence (source_column)
    and chi_square (column_a / column_b)
  ⚠ number_of_rows(threshold := 10) passes only with MORE than 10 rows
  ⚠ accepted_values / not_accepted_values use [NOT] IN → NULL rows always PASS.
    pair with not_null
  ⚠ not_null_proportion(threshold := 0.9) needs > 90% non-null
  ⚠ regex audits use REGEXP_LIKE — check the engine supports it after transpile
  ⚠ unique_values on (a, b) checks a alone and b alone — for the grain you want
    unique_combination_of_columns
  ⚠ min_v / max_v: give at least one; the other defaults to NULL (unbounded)
```

## Scope on incremental models

For kinds with a `time_column` (INCREMENTAL_BY_TIME_RANGE), `@this_model` is the table
**filtered to the interval just processed**. Uniqueness and row counts are checked per
interval, not across the whole table. Other kinds audit the whole table.

## Custom audits

A `.sql` file in `audits/`, or an `AUDIT` block in the model file after the query.

```sql
AUDIT (
  name assert_positive_amount,
  dialect postgres,           -- optional
  blocking false,             -- optional, default true
  defaults (threshold = 0)    -- optional. note `=`
);
SELECT * FROM @this_model WHERE @column <= @threshold;
```

```
  AUDIT properties   name · dialect · blocking · skip · standalone · defaults
  use site           audits (assert_positive_amount(column := amount, threshold := 10))
  skip true          disables the audit everywhere
  @this_model        the model's physical table (interval-filtered as above)
  any @var           filled from defaults, overridden by use-site args
```

## Standalone audits

`standalone true` in the AUDIT block. Not attached to a model — runs on its own during
plan/run, can query several models (reference them by name). **Cannot be blocking**
(source raises `Standalone audits cannot be blocking`). Use for cross-model checks.

**The MCP's `validate` only accepts model files.** Put a custom audit inline in the
model file, or propose the `audits/` file for a person to add.

## Choosing

Encode the risk the business cares about. Grain uniqueness first
(`unique_combination_of_columns`). Then `not_null` on keys a join depends on,
`accepted_values` + `not_null` on categoricals you filter on, `accepted_range` on rates
and amounts, `number_of_rows` where empty output would be a silent failure. Skip audits
that can't fail.
