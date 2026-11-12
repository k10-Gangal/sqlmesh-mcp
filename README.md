# SQLMesh agent — package, context and getting started

Read this first. It is written so a new person, or Claude, can pick the project up
without the history. Last updated 2026-11-12.

---

## 1 · What this is

An AI agent that **writes SQL transformations for a warehouse and proves the warehouse
accepts them — but never applies anything.** A person applies the result.

```
  user ──► agent (TrueForge) ──► MCP server ──► warehouse
           prompt + skill        3 tools         read-only login
                                 stateless
```

Three parts, and only these three are needed to run it:

| Part | What it is | Source folder |
|---|---|---|
| **Agent prompt** | How the agent behaves: rules, playbooks, tone | `agent/AGENT.md` |
| **Skill: sqlmesh** | SQLMesh facts: syntax, kinds, macros, audits, engines, errors | `skills/sqlmesh/` |
| **MCP server** | The three tools the agent calls | `mcp/` |

Also in the package: `eval/questions-v2.md`, the 20 test questions (grader's file — see §7).

Not in the package: the launcher (a form that starts one MCP container per connection),
the old v1 MCP, the design docs and the test data.

---

## 2 · Design decisions, and why

| Decision | Why |
|---|---|
| **The agent never plans or applies.** No such tool exists. | A wrong SQL answer is text a person reads; a wrong *apply* writes tables silently. Splitting them keeps the cost of a mistake small. |
| **Phase 2 (agent applies, behind approval) was dropped.** | Not needed. An earlier platform design (sessions, workspaces, prod approval) existed and is not part of this package. |
| **MCP is stateless, three tools.** Nothing is stored; the agent sends the SQL on every `validate`. | Any container can serve any call. Kill and restart loses nothing. v1 stored models in Postgres (9 tools) — retired. |
| **One MCP container per connection**, each person registering their own login. | The warehouse enforces each person's access. The MCP has no login of its own — whoever has the URL acts as that database user. |
| **The agent sees metadata only:** table and column names, types, descriptions. Never rows, counts or values. | Realistic for a real warehouse, and safe. Consequence: it cannot confirm a filter value, so it must ask. |
| **One model/query per answer. No staging / intermediate / marts layers.** Steps are CTEs. | Each extra model was another validate call that resent every upstream model's SQL — the main cause of slow runs. |
| **Answers are fenced ```sql code blocks, never files.** | The agent was writing files because the prompt asked for them. |
| **Validate once the model is complete,** not after each small edit. | Fewer calls. The "never call it valid until `validate` is clean" rule is unchanged. |

---

## 3 · The MCP server (`mcp/server.py`)

### Tools

| Tool | Returns |
|---|---|
| `list_tables()` | dialect, which engine reference file to read, and the tables **this login can read**, grouped by schema |
| `describe_table(table)` | columns with type and description, plus the table description. Nested JSON/struct fields as dot paths |
| `validate(target, files)` | steps `parse → load → render → tables → lint → explain`, each ok/fail, plus the rendered SQL |

`files` is a map of model name → full model text. In practice it holds the target only.

### How `validate` works
Builds a temporary SQLMesh project (DuckDB state in memory) → loads it → renders it →
checks every table it reads is real → lints → runs **`EXPLAIN`** (Postgres) or a
**dry run** (BigQuery) on the warehouse. EXPLAIN plans the query and never runs it, so
no rows are read. The plan text is not returned. Clean means *the warehouse accepts
the SQL* — it does not mean the numbers are right.

`validate` needs a `MODEL (...)` block to parse. SQLMesh has no plain-SQL mode: a file
without one fails with `ConfigError: Failed to load model`. For plain SQL, the agent
wraps the query inside the tool call only (`MODEL (name x.y, kind FULL); <query>`).

### Access
- **Postgres:** the catalog is filtered to what the login can actually `SELECT`
  (schema `USAGE` + column privileges). Tested with a limited role.
- **BigQuery / MySQL:** their catalogs already filter by permission. **Not tested.**
- **Redshift:** the old unfiltered listing. Not covered.

### Config (environment variables)

| Variable | Meaning |
|---|---|
| `CONNECTION_JSON` | **Required.** SQLMesh connection config, e.g. `{"type":"postgres","host":"…","port":5432,"database":"…","user":"…","password":"…"}` |
| `SOURCE_SCHEMAS` | Comma-separated schemas to expose. Empty = all non-system schemas |
| `MCP_PORT` | Default `8090` |
| `SCHEMA_CACHE_TTL_S` | Table-list cache, default `600` — a new table can take up to 10 minutes to show up |
| `MAX_FORK_WORKERS` | Defaults to `1` inside the server. **Do not raise it** (see §6) |

Health: `GET /health` → `{"ok": true, "dialect": "…"}`. Endpoint: `POST /mcp` (streamable HTTP, stateless, JSON responses).

### Known security gaps (fine locally, not for hosting)
- No authentication — the URL is the credential.
- Credentials live in the container's environment (`docker inspect` shows them).
- DNS-rebinding protection is off.
- Nothing checks that the login is read-only. If it can write, "never writes" rests on the agent having no write tool.

---

## 4 · The agent prompt (`agent/AGENT.md`)

Sections: identity · scope · who you're talking to (asker / author / approver) · how to talk ·
hard rules · tools · playbooks A–F · what validation proves · SQLMesh mental model ·
decision guides · failure modes that pass validation · done-means · skill index.

Rules that matter most:

| # | Rule |
|---|---|
| 1 | Never plan, apply, run, backfill or restate. Explain who does. |
| 2 | `describe_table` every source table before writing. |
| 4 | Never call a model valid until `validate` is clean. **Validate once the model is complete**, not after each edit. |
| 5 | You never see data. Never invent a filter value; a value in a description is a hint, not proof. Ask. |
| 8 | Hand over exactly the SQL you last validated. |
| 10 | **One model or query per answer**, reading sources directly; steps are CTEs; `validate` files = the target only. |
| 11 | **Code only as fenced blocks in the reply. Never a file.** |

### ⚠ Unresolved: SQL-only vs model
`AGENT.md` §2 contains a **"SQL only"** block that says: hand over the query only, never a
`MODEL` block, no macros — and it overrides everything else. But §5-rule-10, §7B, §7F,
§9, §10 and §12 still describe building models (kind, grain, audits). **The prompt
contradicts itself.** The agent sometimes returns SQL, sometimes full models.

The proposed fix (not yet applied): a two-mode switch.
- **SQL** (default): plain query, no `MODEL` block, no macros.
- **MODEL**: when the user asks for something scheduled, incremental, audited or reusable, or says "as a model".
- The user's words decide; an explicit request always wins; never ask which mode before building.
- Macros (`@start_ds`) are banned only in SQL mode. Model-only sections apply only in model mode.

Decide the default, then apply it.

---

## 5 · The skill (`skills/sqlmesh/`)

`SKILL.md` indexes eleven references: `model-syntax`, `kinds`, `macros`, `audits`, `tests`,
`python-models`, `plans-envs`, `linter`, `conventions`, `errors`, plus
`engines/postgres.md` and `engines/bigquery.md`. The agent reads **one file at a time**,
on demand; `list_tables` names which engine file applies. Targets SQLMesh 0.236.x.

`conventions.md` was changed: "Layers" → **one model per question**; "Files" → **Output:
a code block, never a file**.

**GitHub:** `github.com/k10-Gangal/skills`, folder `sqlmesh-skill/`.
Branch `sqlmesh-skill-one-model` holds the `conventions.md` + `SKILL.md` change —
**open it as a PR and merge it.** The agent prompt is not in that repo yet.

---

## 6 · What went wrong, and how it was found

| Symptom | How it was found | Cause | Fix |
|---|---|---|---|
| `validate` — then every tool — timed out (MCP error -32001) | Called all three tools directly: all hung at 120 s, `/health` fine. A second MCP on the same image answered in 0.36 s. Inside the hung container: 355 stuck processes, 5.7 GB RAM, 59 leftover temp dirs | SQLMesh forks worker processes when loading a project. Forking from a threaded server can copy a held lock into the child, which waits forever. Stuck calls pile up until no worker thread is free | `MAX_FORK_WORKERS=1` set in `server.py` before SQLMesh imports; image rebuilt. 15 consecutive validates leave no stuck processes. **Not load-tested.** |
| "Payload too big" blamed by the agent | A 2-column probe also timed out | It was the hang above. Payload size was a coincidence | none needed |
| "The agent is slow" | Timed each `validate` step on a 168-col staging + 123-col mart: **0.24–0.77 s total** | The MCP isn't slow. The agent re-typed every upstream model's SQL on every call (~10,000 tokens per mart validation, estimated) | One model per question; `validate` gets the target only; validate once per complete model |
| Agent produced files | Read the prompt | §2 and §7F told it to "hand over files" | Rule 11 and wording fixes |
| Agent built staging / intermediate / marts | Read `conventions.md` | The skill defined those layers (`intermediate` came from the model's dbt habits) | Layers removed |

Still unmeasured: where the rest of the agent's wall-clock goes — harness, sandbox,
max steps, thinking time. The MCP is ruled out.

---

## 7 · Evaluation

- **`eval/questions-v2.md`** — 20 questions on the four test tables, with the trap
  and the correct answer for each. **Grader's file: never put it in the agent's context.**
  Registers: not-knowing-the-data (6), knows-the-business (9), knows-exactly-what-they-want (5).
  Exams: Q2 voicemail (invented value), Q11 p95 (fake arithmetic), Q15 NULL trap, Q16 build-don't-interrogate.
- **v1 eval (pharmacy IVR dataset, 11 questions)** was run earlier and is not in this package.
  It scored 5/10 as originally graded, 8/10 after the rubric was revised post-run. **It has never been run on v2.** Treat v1 numbers as history.
- **Test data (local Postgres only):** `raw.x42_opportunity_audit` (1,000 sessions),
  `raw.x42_opportunity_events` (3,911), `raw.haio_test_service_sessions` (1,000),
  `raw.x42_pcw_mc_ivr_raw_events_table` (8,282) — dummy rows, with column descriptions
  set as `COMMENT`s. `raw.mc_ivr_sessions` (168 columns, MinuteClinic IVR sessions) exists
  **empty**. None of this data is in the package or the VDI; the questions assume those
  tables, so adapt them to your own tables.

---

## 8 · Getting started

### 8.1 Prerequisites
Python 3.12 + pip · a path to PyPI or an internal mirror (SQLMesh, the MCP SDK and the
database drivers) · network access from the machine to the warehouse host and port ·
Docker only if you want the container or the launcher.

### 8.2 Run the MCP without Docker
```bash
cd mcp
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export SOURCE_SCHEMAS=raw
export CONNECTION_JSON='{"type":"postgres","host":"<host>","port":5432,"database":"<db>","user":"<read-only user>","password":"<password>"}'
python server.py                                          # → http://localhost:8090/mcp
```
Or, simpler: copy `.env.example` to `.env`, fill it in, and run `./run.sh` (Linux/macOS)
or `./run.ps1` (Windows). They create the venv, install, and start the server.
Use a **read-only login**, and the login of the person who will use the agent.

### 8.3 Run it in Docker
```bash
docker build -t sqlmesh-mcp-v2 mcp
docker run -d --name sqlmesh-mcp -p 8090:8090 \
  -e SOURCE_SCHEMAS=raw -e CONNECTION_JSON='{...}' sqlmesh-mcp-v2
```
From inside another container, use the Docker host name, not `localhost`.

### 8.4 Check it works
```bash
curl -s localhost:8090/health        # {"ok": true, "dialect": "postgres"}
curl -s -X POST localhost:8090/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_tables","arguments":{}}}'
```
You should see the dialect and your tables in well under a second. Then call
`describe_table` on one table, then `validate` with a two-line model:
```
MODEL (name scratch.probe, kind VIEW);
SELECT <col>::TEXT AS <col> FROM <schema>.<table>
```
All six steps should be `ok`.

### 8.5 Connect the agent (TrueForge)
1. Add a remote MCP connector: `{"type":"remote","name":"sqlmesh","url":"http://<host>:8090/mcp"}`.
2. Paste `agent.md` as the agent's system prompt.
3. Attach the `skills/sqlmesh/` folder as a skill.
4. Ask: *"What tables do I have?"* — it should call `list_tables` and answer. Then run a few
   questions from `eval/questions-v2.md` (paste only the Prompt line).

TrueForge masks some column names in tool input (it turned `patient_id` into `*******_id`).
A parse error on a name you didn't write usually means that.

---

## 9 · Open items and next steps

1. **Decide the default output mode** (SQL or model) and apply the two-mode block to `AGENT.md`.
2. **Get the agent into TrueForge.** Until it loads the current `AGENT.md` and skill, none of the prompt fixes apply. Merge the skill PR; add `AGENT.md`.
3. **Stabilise:** load-test the fork fix with parallel validates, add a per-call time limit on `validate`, auto-restart a container that stops answering.
4. **Reduce cost and tokens:** measure one real run (input tokens, output tokens, tool calls) as a baseline; then cast only changed columns, cap skill-file reads and steps per question.
5. **Benchmark models:** run the 20 questions on each model → table of pass rate, tokens, time, cost.
6. **Host in CVS:** add authentication, move passwords to a secret manager, turn DNS-rebinding protection back on, require a read-only role at registration.
7. **Adjust the agent to the Guna framework** — framework not yet defined in this repo; get its spec first.
8. **Test BigQuery and MySQL** (descriptions, visibility, dry run); add a Redshift filter.
9. **Backlog:** edit an existing model, improve a pasted SQL query, partial output instead of the whole query, other model kinds.

---

## 10 · Rules of thumb for whoever continues

- **Measure before fixing.** The "slow MCP" was 0.2–0.8 s; the slowness was elsewhere.
- **Never put `questions-v2.md` or any answer key in the agent's context.**
- **Never commit credentials.** Keep any file with passwords (including your `.env`) out of any repo.
- **Rebuild the image after editing `server.py`** and recreate containers with the same name and port so URLs don't change.
- **Do not raise `MAX_FORK_WORKERS`.** It reintroduces the hang.
- **A passing `validate` proves the warehouse accepts the SQL, nothing more.** Grain, joins, NULLs and arithmetic still need checking.
