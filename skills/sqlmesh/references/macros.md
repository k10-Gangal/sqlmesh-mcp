# Macros

> SQLMesh 0.236.x. SQLMesh macros (`@`) are preferred over Jinja.
> Verified against the 0.236.3 source (core/macros.py) and the official docs, 2026-10-26.

## Time variables — `@<prefix>_<postfix>`, all 27 combinations exist

```
  prefix    start · end (inclusive interval) · execution (run start; latest_* = deprecated)
  postfix   value (daily interval 2025-01-01)              renders as
  ds        '2025-01-01'                                   string   ← DATE / string-date cols
  date      date(2025-01-01)                               CAST(... AS DATE)
  ts        '2025-01-01 00:00:00'   end: '...23:59:59.999999'  string, no tz
  tstz      '2025-01-01 00:00:00+00:00'                    string, with offset
  dt        tz-aware datetime (UTC)                        CAST(... AS TIMESTAMPTZ)
  dtntz     naive datetime                                 CAST(... AS TIMESTAMP)  ← TIMESTAMP cols
  hour      0–23                                           int
  epoch     1735689600.0   seconds                         ⚠ float, not int
  millis    1735689600000                                  int
```

All UTC. Intervals are **inclusive on both ends**: `@end_*` = exclusive end − 1µs
(1ns on T-SQL), so `@end_ds` of a daily interval is that same day.
`WHERE d BETWEEN @start_ds AND @end_ds` and `ts BETWEEN @start_ts AND @end_ts` are both correct.

## Runtime variables

```
  @this_model       quoted physical table of this model
                    · in on_virtual_update → the env's qualified VIEW name
                    · in audits on a time-column model → time-filtered subquery
  @runtime_stage    loading | creating | evaluating | promoting | demoting |
                    auditing | testing | before_all | after_all
  @gateway          current gateway name
  @model_kind_name  e.g. FULL, INCREMENTAL_BY_TIME_RANGE (for model_defaults props)
  @this_env @schemas @views     ⚠ only inside before_all / after_all statements
```

⚠ Models are rendered at `loading` too: gate side-effects with `@runtime_stage = 'evaluating'`.

## Interpolation: `@x` vs `@{x}`

```sql
@DEF(x, 'col');
SELECT @x AS a              -- 'col'        value → literal
SELECT @{x} AS a            -- col          value → identifier
SELECT @{x}_cnt, my_@{x}_c  -- col_cnt, my_col_c   braces needed inside a name
SELECT col_@x               -- col_col      only works as a suffix
SELECT @'prefix_@{x}'       -- 'prefix_col' @'...' = templated string literal
FROM @SQL(@tbl)             -- foo.bar      ⚠ @tbl / @{tbl} give ONE quoted ident "foo.bar"
```

Variable names are case-insensitive. Undefined `@x` → error `Macro variable 'x' is undefined`.
Precedence: `@DEF` locals > blueprint vars > gateway vars > root config vars.

## Control operators

```sql
@DEF(min_amount, 10);                     -- after MODEL(...);, before the query, ends with ;
@DEF(add, (a, b) -> a + b);               -- lambda macro; call as @add(1, 2)
@IF(cond, then[, else])                   -- ⚠ no else + false → renders NOTHING
@EACH(['a','b'], x -> expr)               -- or @EACH(@list_var, ...); x→'a', @{x}→a
@REDUCE([...], (a, b) -> a + b)           -- '1 + 2 + 3' (unevaluated SQL)
@FILTER([...], x -> x > 1)                -- items where lambda is true
@EVAL(1 + @n)                             -- evaluate now → 6
@SQL('@x || 1')                           -- string (with @vars) → parsed SQL
SELECT @EACH(['a','b'], x -> SUM(CASE WHEN k = x THEN 1 END) AS @{x}_count) FROM t
@IF(@runtime_stage = 'evaluating', ALTER TABLE @this_model ADD COLUMN c INT);  -- inner stmt: no ;
```

## Conditional SQL clauses — `@CLAUSE(cond) <clause body>`; false drops the whole clause

```sql
@WITH(@flag) c AS (SELECT ...) SELECT ...
SELECT ... FROM t LEFT @JOIN(@flag) u ON t.id = u.id      -- after LEFT/OUTER/etc.
SELECT ... FROM t @WHERE(@region = 'us') a = 1
          @GROUP_BY(@agg) a @HAVING(@agg) COUNT(*) > 1
          @ORDER_BY(TRUE) a @LIMIT(@dev) 10
```

⚠ Replaces the keyword — one per query level; `WHERE x @WHERE(...) y` fails ("multiple '@'
clauses"). To add an optional predicate to an existing WHERE:
`WHERE a = 1 AND @AND(b > 0, @IF(@flag, c > 1))`.

## Built-in helpers (kwargs use `:=`)

```
  @STAR(rel, alias, exclude := [c1], prefix := 'p_', suffix := '',
        quote_identifiers := TRUE)        explicit cols, CAST to known types
  @GENERATE_SURROGATE_KEY(c1, c2, ..., hash_function := 'MD5')
                                          hash of COALESCE(CAST(c AS TEXT),'_sqlmesh_surrogate_key_null_') joined by '|'
  @SAFE_ADD(a, b, ...) · @SAFE_SUB(...)   NULLs → 0; NULL only if ALL args NULL
  @SAFE_DIV(a, b)                         a / NULLIF(b, 0)
  @UNION([cond,] ['all'|'distinct',] t1, t2, ...)
                                          default ALL; only cols with same name AND type;
                                          cond false → SELECT from t1 only
  @DEDUPLICATE(rel, [c1, CAST(ts AS DATE)], ['updated_at DESC', 'id'])
                                          ⚠ order_by = non-empty list of STRINGS → QUALIFY ROW_NUMBER()=1
  @DATE_SPINE('day'|'week'|'month'|'quarter'|'year', 'YYYY-MM-DD', 'YYYY-MM-DD')
                                          query, column date_<part>, both ends inclusive
  @PIVOT(col, ['a','b'], alias := TRUE, agg := 'SUM', cmp := '=',
         prefix := '', suffix := '', then_value := 1, else_value := 0,
         quote := TRUE, distinct := FALSE)
  @HAVERSINE_DISTANCE(lat1, lon1, lat2, lon2, 'mi'|'km')
  @AND(c1, c2, ...) · @OR(...)            drop NULL args; ⚠ all NULL → TRUE (both)
  @RESOLVE_TEMPLATE('s3://b/@{catalog_name}/@{schema_name}/@{table_name}',
                    mode := 'literal'|'table')   no-op at loading
  @VAR('name'[, default]) · @BLUEPRINT_VAR('name'[, default])
```

`@STAR`/`@UNION` need upstream schemas (at load: `__schema_unavailable_at_load__`).
`@STAR` is the sanctioned way around `noselectstar` — it expands to explicit columns.

## Global variables

```yaml
variables:                    # root config
  region: us
gateways:
  prod:
    variables: {region: eu}   # overrides root by key when this gateway is active
```

`@region` or `@VAR('region', 'us')` (name must be a quoted string; missing + no default → NULL).
Bare `@region` when undefined → error; prefer `@VAR` with a default.
Changing a variable a model references changes that model's fingerprint.

## Python macros

A `.py` file in `macros/` (needs `macros/__init__.py`):

```python
from sqlglot import exp
from sqlmesh import macro            # = sqlmesh.core.macros.macro

@macro()                             # or @macro("NAME"), @macro(metadata_only=True)
def is_recent(evaluator, column: exp.Column, days: int = 7):
    return f"{column} >= CURRENT_DATE - INTERVAL '{days}' DAY"
```

```
  arg 1           evaluator: MacroEvaluator (always)
  unannotated     arrives as a SQLGlot expression; annotated (int/str/SQL/list[..]/exp.*) → coerced
  call kwargs     @is_recent(ts, days := 30)
  return          str (parsed) | exp | list of same role | None (removes node)
  evaluator.      runtime_stage · this_model · gateway · var(n, d) · blueprint_var(n, d)
                  columns_to_types(model) · resolve_table(name) · parse_one(sql) · dialect
                  engine_adapter  ⚠ raises at loading
```

**The MCP's `validate` only accepts model files** — a model calling a custom macro
fails with "Macro 'x' does not exist". Propose the macro code; a person adds it.

## Jinja

```sql
JINJA_QUERY_BEGIN;                    -- the model query
SELECT * FROM t WHERE d BETWEEN '{{ start_ds }}' AND '{{ end_ds }}';
JINJA_END;

JINJA_STATEMENT_BEGIN;                -- pre/post statements
GRANT SELECT ON {{ this_model }} TO ROLE r;
JINJA_END;
```

Bare names, no `@`: `{{ start_ds }}`, `{{ this_model }}`, `{{ runtime_stage }}`,
`{{ var('x', default) }}`, `{{ blueprint_var('x') }}`, `{{ gateway() }}` (a function).
No `ref()` outside dbt projects; don't mix Jinja and `@` in one model. Use only when
porting dbt code — Jinja blocks lose column-level lineage.
