# Plans, environments, changes

> SQLMesh 0.236.x. **You explain these. You never run them.**
> Verified 2026-10-26 against installed 0.236.3 source (`core/plan/`, `core/snapshot/definition.py`,
> `core/context.py`, `cli/main.py`, `core/constants.py`) and sqlmesh.readthedocs.io/en/stable.

## Snapshots and fingerprints

A snapshot = one model at one version. Fingerprint has four parts:

```
  data_hash             query, pre/post statements, kind + params, columns,
                        partitioned_by, clustered_by, lookback, interval unit
  metadata_hash         owner, description, column_descriptions, tags, audits,
                        cron, start/end, retention, batch_size, grants
  parent_data_hash / parent_metadata_hash   the same, for all upstream models
```

**Physical table version = hash(data_hash, parent_data_hash).** Metadata never picks
the table. Edit upstream logic → every downstream fingerprint changes too.
Formatting / comment / keyword-case edits change the text but render the same
query → categorised METADATA, no rebuild.

## Environments and naming

```
  prod             the only production env. `sqlmesh plan` with no name = prod.
  any other name   dev env. created by the first plan into it (copied from prod,
                   or `--create-from <env>`). Name is lower-cased on Postgres.

  layer      prod                    dev env `dev`
  virtual    marts.orders  (view)    marts__dev.orders  (view)
  physical   sqlmesh__marts.marts__orders__<version>   (shared by both)
             dev-only (non-deployable) tables add `__dev`
```

`environment_suffix_target`: `schema` (default, above) · `table` → `marts.orders__dev`
· `catalog`. A dev env is cheap: unchanged models' views point at prod's tables.

## Plan

1. Diffs local models against the target env's snapshots.
2. Categorises each change (below). Shows diffs and models to backfill.
3. On apply: creates physical tables, backfills missing intervals, runs audits,
   repoints the env's views (virtual update).

**A plan into dev is a write.** It creates tables and runs queries.
Dev plans backfill only modified/added models unless `--include-unmodified`.

```
  sqlmesh plan [ENV]          flags (cli/main.py)
  -s/--start -e/--end         backfill range; dev only (prod: "The start and end
                              dates can't be set for a production plan without
                              restatements.")  · --execution-time = fake "now"
  --create-from ENV           base for a new env (default prod)
  -r/--restate-model SEL      restate SEL + all downstream (repeatable; tags ok)
  --select-model · --backfill-model · --include-unmodified   scope the plan
  --forward-only · --effective-from DATE · --enable-preview  forward-only
  --allow-destructive-model SEL · --allow-additive-model SEL
  --skip-backfill/--dry-run   virtual update only · --empty-backfill: none, but
                              intervals marked done · --no-gaps
  --auto-apply --no-prompts   non-interactive (fails if anything uncategorised)
  --no-auto-categorization · --explain · --diff-rendered · --no-diff
  --run [--ignore-cron] (prod) · --skip-tests · --skip-linter · --min-intervals N
```

⚠ `--dry-run` is NOT a dry run — it is an alias of `--skip-backfill` and still
repoints views. The read-only option is `--explain` (or just don't apply).

**Promotion to prod**: snapshots already built in dev are reused — prod just
repoints views, no recompute. Exception: forward-only dev data is a preview only.

## Change categories (exact enum, `SnapshotChangeCategory`)

```
  BREAKING              direct. new table; this model + all downstream rebuild.
                        auto: anything not provably additive, or kind change,
                        or SQLMesh can't render / infer downstream columns.
  NON_BREAKING          direct. only adds projections. this model rebuilds;
                        downstream does not.
  INDIRECT_BREAKING     downstream of a (indirect-)breaking parent. rebuilds.
  INDIRECT_NON_BREAKING downstream of non-breaking only. reuses its table.
  METADATA              metadata-only (or all upstream metadata-only).
                        reuses table, no backfill.
  FORWARD_ONLY          deprecated enum value. Forward-only is now a FLAG on a
                        snapshot with one of the categories above: it reuses
                        the existing table; new logic applies to new intervals
                        only — old rows keep old logic.
```

Auto-categorisation is ON by default (mode FULL for sql). It only proves
NON_BREAKING for pure projection additions; everything else defaults to BREAKING.
With `--no-auto-categorization` the person running the plan chooses.
Every change summary states: category + which downstream models rebuild.

**Forward-only schema changes**: `on_destructive_change` (drop column, narrow
type) `error` (default) · `warn` · `allow` · `ignore`; `on_additive_change` same
values, default `allow`.

## Run

`sqlmesh run [ENV]` processes intervals due by cron using the snapshots **stored
in the env's state** — never local code; only `plan` picks up changes. On prod it
also runs the janitor (unless `--skip-janitor`). Flags: `-s/-e` · `--ignore-cron` ·
`--select-model` · `--no-auto-upstream` · `--exit-on-env-update`.

## Restatement

`sqlmesh plan -r marts.orders_daily --start 2025-03-01` re-processes past
intervals (e.g. source data corrected):
- Cascades to **every** downstream model; ranges widen to whole intervals of
  coarser downstream models (hourly → full day).
- Restatement plans ignore local code changes — they work purely from state.
- prod: clears those intervals for all versions of the model (other envs too),
  backfills only prod's current version. Dev envs are not re-run — `sqlmesh run <env>`.
- dev: only the env's own versions. Models whose current version is prod's are
  skipped with a warning ("…current version is used in production…").
- Skipped with a warning when `disable_restatement` is true — the default for
  `INCREMENTAL_UNMANAGED` and the `SCD_TYPE_2*` kinds. Seeds are skipped.

## Janitor and TTL

```
  environment_ttl   "in 1 week" (default). set at each dev plan → it is 1 week
                    since the LAST plan into that env. prod never expires.
                    `environment_ttl: null` disables expiry.
  snapshot_ttl      "in 1 week" (default) for snapshots no env references.
  sqlmesh janitor   drops expired envs' views/schemas and expired snapshot
                    tables. --ignore-ttl · --force-delete · -e/--environment
  sqlmesh invalidate ENV [--sync]   expire an env now
```

Data in an expired dev env is gone; rebuilding it costs a full backfill.

## Concurrency — ConflictingPlanError

No lock on plan creation. Two plans into the same env can both start; at
promotion the slower one fails if another plan was applied meanwhile:
"Another plan (…) was applied to the target environment '<env>' while your
current plan (…) was still in progress, interrupting it. Please re-apply your
plan to resolve this error." Also raised when another plan deploys new versions
during a restatement. Fix: re-plan. Prevention: one dev env per person.
