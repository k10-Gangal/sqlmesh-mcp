# Python models

> SQLMesh 0.236.x.
> Verified against the 0.236.3 source (core/model/decorator.py, core/context.py) and the official docs, 2026-10-26.

**The MCP's `validate` checks SQL models only.** Explain Python models, propose
the code, say it is unvalidated, and a person adds the file. Prefer SQL whenever SQL
can express it.

**When justified:** API calls, ML inference, logic SQL can't express. Not for anything a
window function or macro can do — Python models lose column-level lineage and SQL dry-run.

## Shape

```python
import typing as t
from datetime import datetime
import pandas as pd
from sqlmesh import ExecutionContext, model
from sqlmesh.core.model.kind import ModelKindName

@model(
    "marts.customer_scores",                              # name (positional)
    kind=dict(name=ModelKindName.INCREMENTAL_BY_TIME_RANGE, time_column="ds"),
    columns={"customer_id": "text", "score": "double", "ds": "date"},   # REQUIRED
    grain="customer_id",
    audits=[("not_null", {"columns": ["customer_id"]})],
)
def execute(
    context: ExecutionContext,
    start: datetime,
    end: datetime,
    execution_time: datetime,
    **kwargs: t.Any,
) -> t.Iterator[pd.DataFrame]:
    src = context.resolve_table("staging.stg_customers")   # also registers the dependency
    df = context.fetchdf(f"SELECT customer_id, ds FROM {src} WHERE ds BETWEEN '{start:%Y-%m-%d}' AND '{end:%Y-%m-%d}'")
    if df.empty:
        yield from ()                     # ⚠ never yield/return an empty frame
        return
    df["score"] = 0.0
    yield df
```

## `@model(...)` arguments

```
  name          1st positional; omit only if model_naming.infer_names: true
  columns       REQUIRED — else ConfigError "Python model must define column schema."
  kind          dict(name=ModelKindName.X, ...); "FULL" string also parses
                ⚠ VIEW, SEED, MANAGED, EMBEDDED don't support Python → ConfigError
  other kwargs  = SQL MODEL properties (cron, owner, grain(s), audits, depends_on,
                column_descriptions, partitioned_by, pre_/post_statements,
                on_virtual_update, signals, gateway, blueprints, tags…); not default_catalog
```

## `execute` contract

```
  called as     execute(context=..., start=, end=, execution_time=, **vars)
  start/end     inclusive datetimes (end = exclusive − 1µs), UTC
  return        one DataFrame (pandas / PySpark / Snowpark / Bigframe)
  yield         DataFrames in batches; REQUIRED if post_statements must run after
  empty output  ⚠ empty DataFrame raises — use `yield from ()`
  variables     context.var("x", default) or a named arg `x: str = "d"`;
                ⚠ NOT readable from **kwargs
```

## ExecutionContext

```
  resolve_table("db.model")   physical name for this env; ALSO adds the dependency
                              ⚠ arg must be resolvable at load time (literal / context.var)
  fetchdf(sql | exp, quote_identifiers=False)   → pandas (PySpark on Spark)
  fetch_pyspark_df(sql)       → PySpark DataFrame
  engine_adapter              .execute(sql), .fetchall(sql), .table_exists(t), .columns(t)
  spark · snowpark · bigframe sessions, when the engine has them
  var(n, d) · blueprint_var(n, d) · gateway · is_restatement · default_dialect
```

⚠ `depends_on=[...]` **replaces** inferred deps — list every upstream (resolve_table no longer adds).
