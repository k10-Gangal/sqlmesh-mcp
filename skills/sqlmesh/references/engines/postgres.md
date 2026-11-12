# Postgres

> Read when `list_tables` reports `dialect: postgres`. Cast with `::TYPE`.
> Verified 2026-10-26 against installed 0.236.3 `core/engine_adapter/postgres.py` +
> `base_postgres.py` + `base.py`, and by running every trap below on Postgres 16.2.

## SQLMesh on Postgres

```
  catalog = DATABASE     single catalog only. cross-db refs fail: "cross-database
                         references are not implemented"
  VIEW materialized true ignored — plain view (no MV support in the adapter)
  clustered_by           silently ignored — don't set it
  partitioned_by         no native partitions; INCREMENTAL_BY_PARTITION works by
                         DELETE+INSERT on the partition columns
  INCREMENTAL_BY_UNIQUE_KEY  native MERGE on PG 15+; below 15 emulated
                         (delete+insert) and `when_matched` / `merge_filter`
                         then error. Only this kind uses MERGE.
  identifiers ≤ 63 chars physical table = `<schema>__<model>__<10-digit ver>`
                         (+`__dev`). keep schema+model name ≲ 40 chars or the
                         build fails: "Identifier name '…' (length N) exceeds
                         Postgres's max identifier limit of 63 characters"
  schemas                physical `sqlmesh__<schema>`; views in `<schema>` (prod)
                         and `<schema>__<env>` per dev env
```

## SQL traps (verified)

```
  integer division     5 / 2 = 2.  num::NUMERIC / NULLIF(den, 0)
  divide by zero       col / 0 → runtime error, passes EXPLAIN. NULLIF(den, 0)
  text col = number    status = 1 → operator does not exist: text = integer.
                       (a quoted literal '1' = 1 is fine — it coerces)
  identifiers          unquoted fold to lower case. "MixedCase" must stay quoted.
  x = NULL             always unknown → zero rows, no error. use IS NULL
  x != 'a'             drops NULL rows. use IS DISTINCT FROM
  NOT IN (subquery)    one NULL in the subquery → zero rows. use NOT EXISTS
  NULL || 'x'          NULL. use CONCAT() or COALESCE
  DATE_TRUNC           never DATE: date in → timestamptz, timestamp in →
                       timestamp. cast ::DATE when you want a date
  date − date          integer days.  d + INTERVAL '1 day' → timestamp
  types                COUNT/SUM(int) → BIGINT · AVG(int) → NUMERIC
  GROUP BY             every non-aggregated column; output alias or ordinal ok
  WHERE                no output aliases, aggregates or window functions
  other dialects       IFNULL/NVL/IIF are rewritten to COALESCE/CASE on render.
                       DATEADD fails (column "day" does not exist).
                       ⚠ DATEDIFF is silently rewritten to AGE(…)::BIGINT —
                       wrong numbers. use (d2 - d1) or EXTRACT(EPOCH FROM …)
  timestamptz          stored UTC, displayed in the session tz
  date spines          generate_series(a, b, INTERVAL '1 day')
```

## EXPLAIN catches / misses

The MCP's explain step runs `EXPLAIN <rendered sql>` with upstream models inlined
(read-only session, statement_timeout). It plans; it never executes.

```
  catches   unknown table/schema/column · ambiguous column · operator/function
            type mismatches · GROUP BY errors · aggregates in WHERE · UNION type
            mismatch · cross-db refs · errors in CONSTANT expressions
            (1/0, 'abc'::INT, '2024-13-45'::DATE, INTERVAL 'banana')
  misses    anything data-dependent: col/0, col::INT on bad values, scalar
            subquery returning >1 row · duplicate output column names ·
            identifier length · x = NULL · wrong grain · empty or wrong results
```
