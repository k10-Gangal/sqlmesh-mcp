# Validation errors

> By the step of `validate` that failed. Fix the cause; never silence it.
> Error text is real output from SQLMesh 0.236.3 and Postgres 16.2, verified
> 2026-10-26/28. BigQuery wording differs — read the message, the causes are the same.

Steps run in order: `parse → load → render → tables → lint → explain`.
parse, load and render stop at the first failure. `tables` and `lint` report and
continue; `explain` is skipped if `tables` found an unknown table.
`detail` is the error chain joined with ` ← `.

## Before any step — tool error

```
  `files` must contain the target X.     put the target model's SQL in `files`
  X not found. Call list_tables().       (describe_table) wrong schema.table
```

## parse — the project didn't load

parse covers loading every model in `files`, so an error in ANY of them lands here.

```
  cause → fix
  ─────────────────────────────────────  ────────────────────────────────────────
  Expecting ). Line 1, Col: N.           missing comma between MODEL properties,
                                         or unbalanced parens → model-syntax.md
  Expected table name but got … text: =  `name = a.b` — properties take no `=`
  Required keyword: 'value' missing      `=` inside kind (…); use a space:
                                         (time_column ds)
  Invalid field name present in the      misspelt property — read the "Did you
   MODEL block: 'ownr'. Did you mean …   mean" suggestion
  Invalid field name … 'kind X' field    param not valid for that kind → kinds.md
  Please add required field 'p' to the   kind needs that param → kinds.md
   MODEL block 'kind X' field.
  Model kind specified as 'X', but …     kind typo; message lists valid kinds
  Only one SELECT query is allowed …     exactly one query per model
  A query is required and must be a      no query, or INSERT/DDL instead
   SELECT statement, …
  Please add a MODEL block / … 'name'    MODEL (…); first, with a name
  Macro 'x' does not exist.              typo or not a built-in → macros.md
  Macro variable 'x' is undefined.       @x with no value → define or use
                                         @VAR('x', default)
  An error occurred during evaluation    bad macro args, e.g. "missing a required
   of 'SAFE_DIV'                         argument: 'denominator'" → macros.md
  Duplicate SQL model name: 'm.a'.       two entries in `files` share a MODEL name
  Detected a cycle in the DAG.           A reads B reads A — restructure
  Audit 'x' is undefined                 custom audit not available — define it
                                         inline in the same file → audits.md
  Invalid cron expression 'x'            → model-syntax.md
  a name like *******_id                 input MASKED upstream. don't guess —
                                         tell the user, describe_table again
```

## load — the target isn't among the loaded models

```
  no model named X — check the MODEL     the `target` argument differs from the
   name                                  MODEL `name` in the file. make them equal
```

## render

Rare. ⚠ `@VAR('x')` with no value and no default does NOT fail: it renders as NULL
(`status = NULL` → zero rows). Check `rendered_sql` for NULLs you didn't write.

## tables — a table is neither a source nor in `files`

```
  unknown: staging.stg_orders            a model the target reads wasn't sent →
                                         add its SQL to `files` (ask the user if
                                         you don't have it)
  unknown: raw.ordrs                     typo / wrong schema → list_tables
```

## lint — error rules (full text in linter.md)

```
  ambiguousorinvalidcolumn: Column 'x'   missing → describe_table, fix spelling;
   could not be resolved …               exists → qualify with the alias
  invalidselectstarexpansion: …          upstream columns unknown → list columns
  Rule x could not be found              bad name in ignored_rules
```

## explain — the warehouse rejected the query plan

Upstream models are inlined, so the error may point into upstream SQL. On Postgres
read the `HINT:` — it often names the right column. On BigQuery this step is a
dry-run job; the message names the problem the same way.

```
  column "x" does not exist              wrong name/case (HINT: Perhaps you meant…)
  relation "s.t" does not exist          wrong table/schema → list_tables
  operator does not exist: text = int…   type mismatch → cast one side
  function f(…) does not exist           not a function in this dialect, or wrong
                                         arg types → engines/<dialect>.md
  column "t.c" must appear in the        add to GROUP BY, or aggregate it
   GROUP BY clause …
  column reference "x" is ambiguous      qualify it
  UNION types X and Y cannot be matched  cast branches to one type
  aggregate/window functions are not     move to HAVING / an outer query
   allowed in WHERE
  invalid input syntax for type …        bad constant ('abc'::INT)
  permission denied                      the read-only role can't see that table —
                                         tell the user; don't work around it
```

## Clean, but still wrong

Not an error — the most important case. See `agent.md` §8 and §11.
