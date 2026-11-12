# Model syntax

> SQLMesh 0.236.x · SQL models.
> Verified against the 0.236.3 source (ModelMeta, dialect parser) and the official docs, 2026-10-26.
> Every separator rule and ⚠ below was tested against the 0.236.3 parser.

## File anatomy

```
  [/* comment */]       optional. becomes `description` if that property is unset
  MODEL ( ... );        must be the FIRST statement, semicolon-terminated
  [pre-statements;]     anything before the query
  SELECT ... ;          EXACTLY ONE query. This is the model.
                        UNION / INTERSECT / EXCEPT of SELECTs = one query
  [post-statements;]    anything after the query. query needs its `;` then
  [ON_VIRTUAL_UPDATE_BEGIN; ...; ON_VIRTUAL_UPDATE_END;]   e.g. GRANT on the view
  [AUDIT (name x); SELECT ...;]   inline audit, usable in this model's `audits`
```

```
  ⚠ 0 queries  → "A query is required and must be a SELECT statement..."
  ⚠ 2+ queries → "Only one SELECT query is allowed per model"
  ⚠ pre/post run TWICE: at table creation and at evaluation. Gate side effects:
      @IF(@runtime_stage = 'evaluating', <stmt>);
  ⚠ inside ON_VIRTUAL_UPDATE, @this_model is the env VIEW (db__dev.x), not the table
```

```sql
MODEL (
  name staging.stg_orders,
  kind VIEW,
  grain order_id,
  description 'One row per order.'
);

SELECT
  order_id::TEXT          AS order_id,     -- order key
  customer_id::TEXT       AS customer_id,
  placed_at::TIMESTAMPTZ  AS placed_at,
  amount::DECIMAL(12,2)   AS amount
FROM raw.orders;
```

Every name above is a placeholder. Real names come from `list_tables`.

## Rules for the final SELECT

```
  ✓ cast every column in the outer-most SELECT (CTEs need not). `x::T` works in any dialect
  ✓ every output column has a unique, inferrable name
      bare 1, x + 1, SUM(x) are not inferrable → alias them
  ✗ no SELECT * in the outer-most SELECT (lint: noselectstar)
  ✓ @STAR(relation, exclude := [c], prefix := 'p_') is NOT flagged by noselectstar;
      it expands to CAST(col AS type) AS col — only if the relation's schema is known
      (upstream model or external_models.yaml). Unknown → one junk column
      `__schema_unavailable_at_load__`. Run create_external_models first.
```

Column types come from the casts. Without them SQLMesh may not know the schema,
and downstream column checks degrade.

Column comments: a trailing `-- comment` on a select item is registered as the
column comment (last comment wins). If `column_descriptions` is set, ALL inline
comments are ignored — use one mechanism, not both.

## Properties

`name` is the only required property. Unknown keys are a hard error:
`Invalid field name present in the MODEL block: '<key>'`. Trailing comma allowed.

```
  name                 schema.model — IDENTIFIER, never a string ('a.b' = parse error)
  kind                 default VIEW. ALWAYS state it.             → kinds.md
  dialect              per-model override of model_defaults.dialect
  description          'string' → table comment
  column_descriptions  (col = 'comment', ...)                     note `=`
  columns              (col TYPE, col TYPE)  — see "columns" below
  grain                ONE unique key: grain id | grain (a, b) = composite key
  grains               SEVERAL keys: grains (a, b) = two single-col keys!
                       composite inside: grains ((a, b), c). don't set both grain+grains
  references           non-unique join keys: references (customer_id)
  audits               (audit_name(arg := value), ...)            note `:=`
  cron                 '@daily' (default) | '@hourly' | '0 6 * * *'. UTC. ≥ 5 min
  cron_tz              'America/New_York' — scheduling only; intervals stay UTC
  interval_unit        year|month|day|hour|half_hour|quarter_hour|five_minute
                       derived from cron by default
  start                '2025-01-01' | '1 year ago' — earliest interval (incrementals)
  end                  same formats. requires `start`
  owner                'name'
  tags                 tag | (tag1, tag2)
  stamp                'string' — forces a new version without a code change
  depends_on           (schema.model, ...) — parens/brackets REQUIRED; only deps
                       SQLMesh can't infer from the query
  partitioned_by       col | (col, col) | DATE_TRUNC('month', col)
                       each expr = exactly one column. required for
                       INCREMENTAL_BY_PARTITION. ✗ on VIEW (unless materialized), EMBEDDED
  clustered_by         col | (col, col) — clustering engines. same kind limits
  table_format         iceberg | delta | hudi … (Spark/Athena-type engines)
  storage_format       parquet | orc … (Spark/Athena-type engines)
  physical_properties  (key = value, ...)  table/view in physical layer. note `=`
                       e.g. (creatable_type = TRANSIENT). old name table_properties
  virtual_properties   (key = value, ...)  env view. e.g. (creatable_type = SECURE)
  session_properties   (key = value, ...)  engine session
  grants               ('select' = ['role_a', 'role_b'], 'insert' = ['etl'])
                       quote the privilege keys (select is a keyword). not on EMBEDDED
  grants_target_layer  virtual (default) | physical | all
  signals              (my_signal(arg := value)) — must be a defined @signal, else error
  blueprints           ((k := v1), (k := v2)) — one model per tuple; put @k in name
  physical_version     'v1' — pins physical table. forward-only models ONLY
  enabled              true by default. false = model skipped at load
  optimize_query       true by default. false only for engine text-limit errors
  allow_partials       false by default — true lets partial intervals run
  gateway              defaults to the default gateway
  ignored_rules        rule | (rule, rule) | ALL — linter rules to skip; justify it
  formatting           false to skip `sqlmesh format`
```

```
  ⚠ do not emit validate_query — deprecated in 0.159.7 (docs), since removed from
      ModelMeta (state migration v0075): now fails "Invalid field name". Use the linter.
  ⚠ not settable in a MODEL block (config/internal ModelMeta fields): project,
      virtual_environment_mode, physical_schema_override, default_catalog, retention
```

### columns

Declares names + types and DISABLES inference from the query. Needed when the
query's types can't be inferred (source schema unknown, @STAR on an unknown
table) or to override a SEED's pandas-inferred types. `name TYPE`, comma-separated:

```sql
MODEL (name staging.stg_x, kind FULL, columns (id INT, status TEXT));
```

A `column_descriptions` key not in `columns` is dropped with a warning.

## Separators — the most common mistake

```
  MODEL / kind properties     key value          name staging.stg_orders
  kind sub-properties         key value          kind INCREMENTAL_BY_TIME_RANGE (time_column ds)
                                                 ✗ (time_column = ds) → ParseError
  column_descriptions         key = value        (order_id = 'the id')   ✗ `:=` crashes
  physical/virtual/session    key = value        (k = v)  ✗ `:=` / bare → error
  grants                      'key' = [list]     ('select' = ['r'])
  AUDIT block defaults        key = value        (threshold = 10)        ✗ `:=` fails
  audit / signal / blueprint  key := value       not_null(columns := (id))
    call arguments
  columns                     name TYPE          (id INT, ts TIMESTAMP)
  lists                       (a, b) or [a, b]   both parse — grain, tags, depends_on,
                                                 audits, SCD `columns`, unique_key
```

## Model defaults

`model_defaults` in project config (needs `dialect`). Keys: kind, dialect, cron,
cron_tz, owner, start, table_format, storage_format, on_destructive_change,
on_additive_change, physical/virtual/session_properties, audits, optimize_query,
allow_partials, enabled, interval_unit, formatting, batch_concurrency,
pre_statements, post_statements, on_virtual_update, gateway.

```
  scalar keys              MODEL value overrides the default
  *_properties             merged per key; MODEL wins. `key = None` drops a default key
  audits                   default audits + MODEL audits (concatenated)
  pre/post/on_virtual_update   default statements run first, then the model's
  on_*_change, batch_concurrency   pushed into `kind` if the kind supports them
```

Still state `kind` explicitly — don't depend on a default the reader can't see.
