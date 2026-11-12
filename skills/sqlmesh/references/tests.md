# Unit tests

> SQLMesh 0.236.x
> Verified against the 0.236.3 source (core/test/definition.py, core/test/runner.py,
> cli/main.py) and the official docs, 2026-10-26.

A test feeds a model fixed input rows and compares its output to expected rows. It
never reads warehouse data — it runs on a test connection (in-memory DuckDB by default).
Tests live in `tests/*.yaml`, run with `sqlmesh test`, and **run automatically on every
`sqlmesh plan`** unless `--skip-tests`.

**This agent cannot run tests or write to `tests/`.** Write the YAML, say it is unrun,
and a person adds it.

## Shape

```yaml
test_orders_daily:                   # test name — must be unique
  model: marts.orders_daily          # required
  description: counts per day        # optional
  inputs:
    staging.stg_orders:              # every upstream model/table the query reads
      rows:
        - order_id: '1'
          placed_at: '2025-01-01 10:00:00'
          region: north
        - order_id: '2'
          placed_at: '2025-01-01 12:00:00'
          region: north
  outputs:
    query:
      rows:
        - order_date: 2025-01-01
          region: north
          order_count: 2
  vars:
    start: 2025-01-01
    end: 2025-01-01
```

## Keys

```
  top level   model (required) · inputs · outputs (required) · vars
              description · gateway (test connection to use) · schema (test schema name)

  inputs.<t>  rows:   list of dicts                   ← the usual form
              query:  SQL that produces the rows      ← not together with rows
              columns: {col: type}                    ← pin types; omitted cols → NULL
              format: yaml (default) | csv
              path:   file holding the rows (yaml or csv)
              csv_settings: {...}                     ← pandas read_csv options
              shorthand: inputs.<t> can be a bare list of rows

  outputs     query:  expected final rows (same forms as an input)
              ctes:   {cte_name: {rows: [...]}}       ← test one CTE alone
              partial: true                           ← at outputs level (all) or per output
              must contain query or ctes, or the test fails to load

  vars        start · end · execution_time · any @VAR the model reads
              execution_time also freezes CURRENT_DATE / NOW() in the query
```

## Comparison rules

```
  order       order-insensitive, UNLESS the query (or CTE) has ORDER BY
  partial     only the columns listed in the expected rows are compared
              without it: every output column must be listed
  columns     a column in rows that the model doesn't output → error
  types       values are coerced to the model's column types; pin with columns: if needed
```

## What to test

The logic that could be wrong: the join that might drop rows, the NULL branch, the
boundary of a date filter, the dedupe. Include at least one row that must be
**excluded** — a test of only happy rows proves little.

## Generating a test from real data (a person runs this)

```
  sqlmesh create_test marts.orders_daily \
    --query staging.stg_orders "SELECT * FROM staging.stg_orders WHERE placed_at::DATE = '2025-01-01'" \
    --var start 2025-01-01 --var end 2025-01-01
  flags  -q/--query <upstream> <sql> (repeat per input) · -v/--var k v · -o/--overwrite
         -p/--path · -n/--name · --include-ctes
```

```
  sqlmesh test [tests/file.yaml::test_name ...]
  flags  -k <pattern> · -v/--verbose · --select-model <m> · --preserve-fixtures · --local
```

Test connection: the gateway's `test_connection`, else `default_test_connection`, else
in-memory DuckDB. SQL is transpiled to it — engine-only functions can fail in tests and
not in prod.
