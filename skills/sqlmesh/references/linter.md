# Linter

> SQLMesh 0.236.x · as configured in the sqlmesh MCP's `validate`.
> Verified 2026-10-26 against installed 0.236.3 `core/linter/rules/builtin.py`,
> `core/linter/definition.py`, and guides/linter docs.

Runs as step `lint` of `validate`, after render, before explain.
Lint failing does NOT stop validation — explain still runs. `valid` needs both.

```
  rule (enabled by the MCP)    level  catches
  ───────────────────────────  ─────  ──────────────────────────────────────────
  ambiguousorinvalidcolumn     error  column not in the known schema, or unqualified
                                      and present in two joined sources
  invalidselectstarexpansion   error  SELECT * where an upstream's columns are unknown
  noselectstar                 warn   SELECT * in the outer-most projection
  nomissingaudits              warn   no `audits` (EMBEDDED/EXTERNAL exempt)
```

Real messages (detail = `rule: message`, errors joined by `; `, then `[warnings]`):
```
  ambiguousorinvalidcolumn: Column 'amnt' could not be resolved. Line: 2, Col: 15
    for model '"db"."m"."a"', the column may not exist or is ambiguous.
  invalidselectstarexpansion: SELECT * cannot be expanded due to missing schema(s)
    for model(s): '"db"."raw"."nosuch"'. Run `sqlmesh create_external_models` …
  noselectstar: Query should not contain SELECT * on its outer most projections,
    even if it can be expanded.
  nomissingaudits: Model `audits` must be configured to test data quality.
```

⚠ The column rules only work when every dependency's columns are known (the MCP
declares every source table it can see). If any dependency is unknown, column
checking is skipped silently. An unknown TABLE is never a lint error — the
`tables` step catches it.
⚠ Same message for "missing" and "ambiguous": if the column exists, qualify it.

## Warnings

Don't fail validation, but treat both as must-fix: explicit columns (or `@STAR`)
instead of `SELECT *`; an audit that tests something real.

## Skipping a rule

```sql
MODEL (
  name staging.passthrough,
  kind VIEW,
  ignored_rules (noselectstar)   -- passthrough of an external table whose
                                 -- columns change; reviewed by <person>
);
```

Accepted: `(a)` · `(a, b)` · `[a, b]` · `'a'` · `ALL` (disables lint for the model).
Names are case-insensitive. An unknown name fails the lint step:
`Rule nosuchrule could not be found`.
Only with a reason in a comment and the user's agreement. Never to turn a failing
validation green — ⚠ it can silence the two error rules too; don't.

## All built-in rules in 0.236.3 (name = class name lower-cased)

```
  ambiguousorinvalidcolumn  invalidselectstarexpansion  noselectstar
  nomissingaudits           — enabled above
  noambiguousprojections    duplicate or un-nameable outer projections
  nomissingexternalmodels   depends on an unregistered external table
  nomissingunittest         model has no unit test in tests/
```

There is no `nomissingowner` rule. Not enabled here ⇒ `SELECT id, id …` passes
every step and only fails when the table is built ("column "id" specified more
than once"). Check projections yourself.
