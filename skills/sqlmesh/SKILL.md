---
name: sqlmesh
description: SQLMesh 0.236.x reference — MODEL syntax, all model kinds, macros, audits, unit tests, Python models, plans and environments, linter rules, Postgres dialect notes, naming conventions, and validation errors with fixes. Read the matching reference before writing any SQLMesh syntax you have not used this session, explaining a SQLMesh concept, or fixing a validation error.
---

# SQLMesh reference

Facts only. How to behave is in `agent.md`. Read **one** file — the one you need.

| Need | File |
|---|---|
| MODEL block, every property, separator rules | `references/model-syntax.md` |
| The 12 kinds — parameters, example, pitfalls | `references/kinds.md` |
| Time macros, `@DEF`/`@IF`/`@EACH`, built-in macros, Jinja, variables | `references/macros.md` |
| Built-in audits, custom audits, blocking | `references/audits.md` |
| Unit-test YAML | `references/tests.md` |
| Python models | `references/python-models.md` |
| Plan, apply, environments, change categories, forward-only, restatement, janitor | `references/plans-envs.md` |
| Linter rules — which error, which warn | `references/linter.md` |
| Engine / dialect rules — read the file `list_tables` names in `engine_reference` | `references/engines/<dialect>.md` (postgres, bigquery) |
| Naming, the one-model rule, output format | `references/conventions.md` |
| Validation error → cause → fix | `references/errors.md` |

Every file states what it was checked against. If something here contradicts
what a tool returns, the tool wins — say so to the user.
