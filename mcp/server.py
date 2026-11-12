#!/usr/bin/env python3
"""
sqlmesh-mcp v2 — stateless. One container = one warehouse connection.

Tools
  list_tables()            tables in the source schemas        (catalog only)
  describe_table(table)    columns · types · descriptions      (catalog only)
  validate(target, files)  parse → load → render → lint → explain

Nothing is stored. No user data is returned: no row counts, no values, no
plans. Descriptions are the warehouse's own column/table comments — metadata
someone wrote, not data. Every validate builds a temp project, runs SQLMesh
with an in-memory DuckDB state, and deletes it.

Config (env, set by the launcher)
  CONNECTION_JSON   SQLMesh connection config, e.g. {"type":"postgres",...}
  SOURCE_SCHEMAS    comma-separated schemas to expose (default: all non-system)
  MCP_PORT          default 8090
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Optional

# SQLMesh forks worker processes when it loads a project. Forking from a server
# that runs tool calls on threads can copy a held lock into the child, which then
# waits forever — the stuck calls pile up until every tool times out. A model is
# tiny, so load it in-process. Must be set before sqlmesh is imported.
os.environ.setdefault("MAX_FORK_WORKERS", "1")

for _n in ("sqlmesh", "sqlglot", "apscheduler"):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from sqlglot import exp
from sqlmesh.core.config import (
    Config, DuckDBConnectionConfig, GatewayConfig, LinterConfig, ModelDefaultsConfig,
)
from sqlmesh.core.config.connection import parse_connection_config
from sqlmesh.core.context import Context

# ────────────────────────────────────────────────────────────── config
CONN = json.loads(os.environ["CONNECTION_JSON"])
DIALECT = CONN["type"]
PORT = int(os.environ.get("MCP_PORT", "8090"))
SCHEMAS_ENV = [s.strip() for s in os.environ.get("SOURCE_SCHEMAS", "").split(",") if s.strip()]
CACHE_TTL_S = int(os.environ.get("SCHEMA_CACHE_TTL_S", "600"))
SYSTEM_SCHEMAS = {
    "information_schema", "pg_catalog", "pg_toast", "mysql", "performance_schema", "sys",
}

# Engine notes live in the skill, one file per dialect. The server only says which
# file applies — the agent reads it there.
ENGINE_REFERENCES = {"postgres", "bigquery"}


def _engine_reference() -> str | None:
    return f"references/engines/{DIALECT}.md" if DIALECT in ENGINE_REFERENCES else None

_adapter_lock = threading.Lock()
_adapter = None


def adapter():
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = parse_connection_config(CONN).create_engine_adapter()
        return _adapter


# ─────────────────────────────────────────────── schema cache (catalog only)
# tables: {"schema.table": {col: type}}
# docs:   {"schema.table": {"table": str | None, "columns": {col or dot.path: str}}}
_cache: dict[str, Any] = {"at": 0.0, "tables": {}, "docs": {}}


def _schemas() -> list[str]:
    if SCHEMAS_ENV:
        return SCHEMAS_ENV
    a = adapter()
    if DIALECT == "bigquery":
        rows = [(d.dataset_id,) for d in a.client.list_datasets()]
    else:
        rows = a.fetchall("SELECT schema_name FROM information_schema.schemata")
    return sorted(r[0] for r in rows if r[0] not in SYSTEM_SCHEMAS and not r[0].startswith("pg_"))


def _load_cache(force: bool = False) -> dict[str, dict[str, str]]:
    if not force and _cache["tables"] and time.time() - _cache["at"] < CACHE_TTL_S:
        return _cache["tables"]
    if DIALECT == "postgres":
        tables, docs = _pg_catalog(_schemas())
        _cache.update(at=time.time(), tables=tables, docs=docs)
        return tables
    a = adapter()
    tables: dict[str, dict[str, str]] = {}
    for schema in _schemas():
        for obj in a.get_data_objects(schema):
            key = f"{schema}.{obj.name}"
            try:
                cols = a.columns(exp.table_(obj.name, db=schema, quoted=True))
                tables[key] = {c: t.sql(dialect=DIALECT) for c, t in cols.items()}
            except Exception:
                tables[key] = {}
    _cache.update(at=time.time(), tables=tables, docs=_descriptions(tables))
    return tables


def _pg_catalog(schemas: list[str]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    """Tables, columns and comments this login can actually read.

    Postgres shows every object in pg_catalog to every user, whatever their
    grants — and SQLMesh's adapter lists from there. Many people share one
    database with their own logins, so keep only schemas with USAGE and columns
    with SELECT (table-level or column-level). A table with no readable column
    is not listed at all.
    """
    a = adapter()
    tables: dict[str, dict[str, str]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for s in schemas:
        lit = exp.Literal.string(s).sql(dialect=DIALECT)
        rows = a.fetchall(
            "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
            "col_description(c.oid, a.attnum), obj_description(c.oid, 'pg_class') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
            f"WHERE n.nspname = {lit} AND c.relkind IN ('r', 'v', 'm', 'p', 'f') "
            "AND has_schema_privilege(n.oid, 'USAGE') "
            "AND has_column_privilege(c.oid, a.attnum, 'SELECT') "
            "ORDER BY c.relname, a.attnum"
        )
        for t, col, dtype, cdesc, tdesc in rows:
            key = f"{s}.{t}"
            try:
                dtype = exp.DataType.build(dtype, dialect=DIALECT).sql(dialect=DIALECT)
            except Exception:
                dtype = dtype.upper()
            tables.setdefault(key, {})[col] = dtype
            d = docs.setdefault(key, {"table": None, "columns": {}})
            if tdesc and tdesc.strip():
                d["table"] = tdesc.strip()
            if cdesc and cdesc.strip():
                d["columns"][col] = cdesc.strip()
    return tables, docs


def _descriptions(tables: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Table and column comments. Best effort: a warehouse without comments, or a
    role that can't read them, just yields no descriptions — never an error."""
    a = adapter()
    docs: dict[str, dict[str, Any]] = {}

    def put(key: str, col: Optional[str], text: Any) -> None:
        if key not in tables or not text or not str(text).strip():
            return
        d = docs.setdefault(key, {"table": None, "columns": {}})
        if col is None:
            d["table"] = str(text).strip()
        else:
            d["columns"][col] = str(text).strip()

    try:
        schemas = sorted({k.split(".", 1)[0] for k in tables})
        if DIALECT == "redshift":  # postgres reads comments in _pg_catalog
            for s in schemas:
                lit = exp.Literal.string(s).sql(dialect=DIALECT)
                for t, col, cdesc, tdesc in a.fetchall(
                    "SELECT c.relname, a.attname, col_description(c.oid, a.attnum), "
                    "obj_description(c.oid, 'pg_class') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_attribute a ON a.attrelid = c.oid "
                    f"AND a.attnum > 0 AND NOT a.attisdropped WHERE n.nspname = {lit}"
                ):
                    put(f"{s}.{t}", col, cdesc)
                    put(f"{s}.{t}", None, tdesc)
        elif DIALECT == "mysql":
            for s in schemas:
                lit = exp.Literal.string(s).sql(dialect=DIALECT)
                for t, tdesc in a.fetchall(
                    "SELECT table_name, table_comment FROM information_schema.tables "
                    f"WHERE table_schema = {lit}"
                ):
                    put(f"{s}.{t}", None, tdesc)
                for t, col, cdesc in a.fetchall(
                    "SELECT table_name, column_name, column_comment "
                    f"FROM information_schema.columns WHERE table_schema = {lit}"
                ):
                    put(f"{s}.{t}", col, cdesc)
        elif DIALECT == "bigquery":
            def walk(key: str, prefix: str, fields: Any) -> None:
                for f in fields:
                    path = f"{prefix}.{f.name}" if prefix else f.name
                    put(key, path, f.description)
                    walk(key, path, f.fields or [])

            for key in tables:
                bq = a.client.get_table(f"{a.client.project}.{key}")
                put(key, None, bq.description)
                walk(key, "", bq.schema)
    except Exception:
        pass
    return docs


def _flatten(prefix: str, dtype: str) -> list[tuple[str, str]]:
    """Expand STRUCT columns into dot paths so nested fields are visible."""
    out = [(prefix, dtype)]
    try:
        dt = exp.DataType.build(dtype, dialect=DIALECT)
    except Exception:
        return out
    if dt.this == exp.DataType.Type.STRUCT:
        for f in dt.expressions:
            kind = f.args.get("kind")
            if kind is not None:
                out += _flatten(f"{prefix}.{f.name}", kind.sql(dialect=DIALECT))
    return out


# ──────────────────────────────────────────────────────────── schemas
class Column(BaseModel):
    name: str
    type: str
    description: Optional[str] = None


class TableInfo(BaseModel):
    table: str
    description: Optional[str] = None
    columns: list[Column]


class Step(BaseModel):
    step: str
    ok: bool
    detail: str = ""


class ValidationResult(BaseModel):
    target: str
    valid: bool
    steps: list[Step]
    rendered_sql: str = ""


# ──────────────────────────────────────────────────────────── server
mcp = MCPServer(
    "sqlmesh-mcp",
    title=f"SQLMesh helper ({DIALECT})",
    # Some clients (TrueForge) ignore server instructions — so list_tables also
    # returns the dialect and engine reference. Keep this a summary, not the source.
    instructions=(
        f"Warehouse dialect: {DIALECT}. Call list_tables first: it returns the dialect and "
        "the engine reference to read. Tools: list_tables → describe_table → validate. "
        "Nothing is stored or applied. You see names, types and descriptions, never data."
    ),
)
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True)


@mcp.tool(annotations=READ)
def list_tables() -> dict[str, Any]:
    """Call first. Returns the warehouse dialect, the engine reference to read before
    writing SQL, and the source tables grouped by schema — only those this
    connection's login is allowed to read."""
    tables = _load_cache()
    grouped: dict[str, list[str]] = {}
    for key in sorted(tables):
        s, t = key.split(".", 1)
        grouped.setdefault(s, []).append(t)
    ref = _engine_reference()
    return {
        "dialect": DIALECT,
        "engine_reference": ref,
        "note": (f"Write every model in {DIALECT} SQL. Read the sqlmesh skill's {ref} before "
                 "writing SQL." if ref else
                 f"Write every model in {DIALECT} SQL. No engine reference exists for "
                 f"{DIALECT} — rely on validate and say so."),
        "tables": grouped,
    }


@mcp.tool(annotations=READ)
def describe_table(table: str) -> TableInfo:
    """Column names, types and descriptions for one table (schema.table). Catalog
    only — no data. Descriptions are the warehouse's comments; missing when none
    were written. Treat them as a hint from whoever wrote them, not as proof."""
    tables = _load_cache()
    if table not in tables:
        tables = _load_cache(force=True)
    if table not in tables:
        raise ToolError(f"{table} not found. Call list_tables().")
    docs = _cache["docs"].get(table, {"table": None, "columns": {}})
    cols: list[Column] = []
    for name, dtype in tables[table].items():
        cols += [
            Column(name=n, type=t, description=docs["columns"].get(n))
            for n, t in _flatten(name, dtype)
        ]
    return TableInfo(table=table, description=docs["table"], columns=cols)


@mcp.tool(annotations=READ)
def validate(target: str, files: dict[str, str]) -> ValidationResult:
    """Validate one model: parse → load → render → lint → explain. Stores nothing.

    Args:
        target: model name to validate, e.g. marts.orders_daily
        files: model name → full model SQL. Include the target and every model it reads.
    """
    if target not in files:
        raise ToolError(f"`files` must contain the target {target}.")
    steps: list[Step] = []

    def done(sql: str = "") -> ValidationResult:
        return ValidationResult(
            target=target, valid=all(s.ok for s in steps), steps=steps, rendered_sql=sql,
        )

    root = Path(tempfile.mkdtemp(prefix="sqlmesh-v2-"))
    try:
        (root / "models").mkdir()
        for name, sql in files.items():
            (root / "models" / f"{name}.sql").write_text(sql)
        ext = [
            {"name": exp.to_table(k).sql(dialect=DIALECT), "columns": v}
            for k, v in _load_cache().items() if v
        ]
        (root / "external_models.yaml").write_text(yaml.safe_dump(ext))
        config = Config(
            gateways={"local": GatewayConfig(
                connection=DuckDBConnectionConfig(),
                state_connection=DuckDBConnectionConfig(),
            )},
            default_gateway="local",
            model_defaults=ModelDefaultsConfig(dialect=DIALECT, start="2024-01-01"),
            linter=LinterConfig(
                enabled=True,
                rules={"ambiguousorinvalidcolumn", "invalidselectstarexpansion"},
                warn_rules={"noselectstar", "nomissingaudits"},
            ),
        )

        # parse + load
        try:
            ctx = Context(paths=root, config=config)
            steps.append(Step(step="parse", ok=True))
        except Exception as e:
            steps.append(Step(step="parse", ok=False, detail=_msg(e)))
            return done()
        model = next(
            (m for m in ctx.models.values() if m.name.replace('"', "").endswith(target)), None
        )
        if model is None:
            steps.append(Step(step="load", ok=False,
                              detail=f"no model named {target} — check the MODEL name"))
            return done()
        steps.append(Step(step="load", ok=True))

        # render — the offline DuckDB gateway prefixes tables with its own catalog
        # ("memory"); swap in the warehouse's catalog, or drop it if it has none.
        try:
            q = ctx.render(model, expand=True)
            wh_catalog = _catalog()
            for t in q.find_all(exp.Table):
                if t.catalog == "memory":
                    if wh_catalog:
                        t.set("catalog", exp.to_identifier(wh_catalog, quoted=True))
                    else:
                        t.set("catalog", None)
            rendered = q.sql(dialect=DIALECT, pretty=True)
            steps.append(Step(step="render", ok=True))
        except Exception as e:
            steps.append(Step(step="render", ok=False, detail=_msg(e)))
            return done()

        # unknown tables — lint doesn't catch these
        known = {k.lower() for k in _load_cache()} | {
            m.name.replace('"', "").split(".", 1)[-1].lower() for m in ctx.models.values()
        }
        refs = {
            f"{t.db}.{t.name}".lower()
            for t in exp.maybe_parse(rendered, dialect=DIALECT).find_all(exp.Table) if t.db
        }
        missing = sorted(r for r in refs if r not in known)
        steps.append(Step(step="tables", ok=not missing,
                          detail=f"unknown: {', '.join(missing)}" if missing else ""))

        # lint
        try:
            vs = ctx.lint_models([model], raise_on_error=False) or []
            errs = [str(v) for v in vs if str(getattr(v, "violation_type", "error")) == "error"]
            warns = [str(v) for v in vs if str(getattr(v, "violation_type", "error")) != "error"]
            detail = "; ".join(errs) + (f" [warn] {'; '.join(warns)}" if warns else "")
            steps.append(Step(step="lint", ok=not errs, detail=detail[:1500]))
        except Exception as e:
            steps.append(Step(step="lint", ok=False, detail=_msg(e)))

        # explain — plans the query, never executes it, returns no plan text
        if not missing:
            try:
                _explain(rendered)
                steps.append(Step(step="explain", ok=True))
            except Exception as e:
                steps.append(Step(step="explain", ok=False, detail=_msg(e)))
        return done(rendered)
    finally:
        shutil.rmtree(root, ignore_errors=True)


_catalog_cache: dict[str, Optional[str]] = {}


def _catalog() -> Optional[str]:
    if "v" not in _catalog_cache:
        try:
            _catalog_cache["v"] = adapter().get_current_catalog()
        except Exception:
            _catalog_cache["v"] = None
    return _catalog_cache["v"]


def _explain(sql: str) -> None:
    a = adapter()
    if DIALECT == "bigquery":
        from google.cloud import bigquery
        a.client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        return
    cur = a.connection.cursor()
    try:
        cur.execute(f"EXPLAIN {sql}")  # plain EXPLAIN — never ANALYZE
        cur.fetchall()
    finally:
        cur.close()
        try:
            a.connection.rollback()
        except Exception:
            pass


def _msg(e: BaseException, limit: int = 3) -> str:
    seen: list[str] = []
    cur: Optional[BaseException] = e
    while cur is not None and len(seen) < limit:
        m = str(cur).strip().splitlines()[0][:400] if str(cur).strip() else ""
        if m and m not in seen:
            seen.append(m)
        cur = cur.__cause__ or cur.__context__
    return " ← ".join(seen) or type(e).__name__


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    from starlette.responses import JSONResponse
    return JSONResponse({"ok": True, "dialect": DIALECT})


if __name__ == "__main__":
    from mcp.server.transport_security import TransportSecuritySettings
    try:
        _load_cache()  # fail fast if the connection or catalog is wrong
    except Exception as e:
        print(f"STARTUP_ERROR: {_msg(e)}", flush=True)
        raise SystemExit(1)
    mcp.run(
        transport="streamable-http", host="0.0.0.0", port=PORT,
        stateless_http=True, json_response=True,
        # Container is reached by its docker name (sqlmesh-mcp-<id>) from TrueForge
        # and by localhost:<port> from the host — names aren't known in advance.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
