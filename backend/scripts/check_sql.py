#!/usr/bin/env python3
"""Statically verifies every SQL string the backend sends to PostgreSQL against the REAL schema.

For each `conn.fetch / fetchrow / fetchval / execute(<sql>, ...)` call it finds in app/ (string literals and
module-level string constants), it asks a throwaway database to PREPARE the statement and EXPLAIN it while
running as the database role the code uses (taken from the enclosing `db.session("role")` / `db.api()` block).
That catches misspelled functions and columns, wrong argument counts or types, and privilege mistakes
(e.g. the API role touching a table it must never read) without running the application.

    PGHOST=... PGPORT=... PGUSER=postgres database/reset_dev_db.sh sadqah     # once
    python backend/scripts/check_sql.py [--db sadqah] [paths...]

Needs only the standard library and the `psql` client. Exit status 1 when any statement fails.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONN_METHODS = {"fetch", "fetchrow", "fetchval", "execute"}
ROLE_FOR_SESSION = {"api": "sadqah_api", "webhook": "sadqah_webhook", "worker": "sadqah_worker", "kyc": "sadqah_kyc", "admin": "sadqah_admin"}


@dataclass
class Query:
    path: Path
    line: int
    sql: str
    role: str | None  # None = role unknown (connection passed in); checked as superuser for names/types only


def _const_strings(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = _literal(node.value, {})
            if val is not None:
                out[node.targets[0].id] = val
    return out


def _literal(node: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _literal(node.left, consts), _literal(node.right, consts)
        return a + b if a is not None and b is not None else None
    return None


def _session_role(call: ast.Call) -> str | None:
    """`db.session("worker", ...)` -> worker; `db.api(...)` -> api; `db.pool("x").acquire()` -> x."""
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr == "api":
            return "api"
        if f.attr == "session" and call.args and isinstance(call.args[0], ast.Constant):
            return str(call.args[0].value)
        if f.attr == "acquire" and isinstance(f.value, ast.Call):
            return _session_role(f.value) or (
                str(f.value.args[0].value) if isinstance(f.value.func, ast.Attribute) and f.value.func.attr == "pool" and f.value.args and isinstance(f.value.args[0], ast.Constant) else None)
    return None


def collect(path: Path) -> tuple[list[Query], list[str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    consts = _const_strings(tree)
    queries: list[Query] = []
    warnings: list[str] = []

    def visit(node: ast.AST, conn_roles: dict[str, str | None]) -> None:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            inner = dict(conn_roles)
            for item in node.items:
                if isinstance(item.context_expr, ast.Call) and isinstance(item.optional_vars, ast.Name):
                    role = _session_role(item.context_expr)
                    if role:
                        inner[item.optional_vars.id] = role
            for child in node.body:
                visit(child, inner)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = dict(conn_roles)
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg in ("conn", "connection"):
                    inner.setdefault(arg.arg, None)
            for child in node.body:
                visit(child, inner)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CONN_METHODS \
                and isinstance(node.func.value, ast.Name) and node.func.value.id in conn_roles and node.args:
            sql = _literal(node.args[0], consts)
            if sql is None:
                if isinstance(node.args[0], ast.JoinedStr):
                    warnings.append(f"{path}:{node.lineno}: f-string SQL cannot be checked (and should not be used)")
                else:
                    warnings.append(f"{path}:{node.lineno}: SQL is not a literal; not checked")
            else:
                queries.append(Query(path, node.lineno, sql, conn_roles[node.func.value.id]))
        for child in ast.iter_child_nodes(node):
            visit(child, conn_roles)

    visit(tree, {})
    return queries, warnings


def check(q: Query, db: str) -> str | None:
    sql = q.sql.strip().rstrip(";")
    params = [int(n) for n in re.findall(r"\$(\d+)", sql)]
    nargs = max(params) if params else 0
    role = ROLE_FOR_SESSION.get(q.role or "")
    script = ["BEGIN;"]
    if role:
        script.append(f"SET LOCAL ROLE {role};")
    script.append(f"PREPARE q AS {sql};")
    script.append("EXPLAIN (COSTS OFF) EXECUTE q" + (f"({', '.join(['NULL'] * nargs)})" if nargs else "") + ";")
    script.append("ROLLBACK;")
    proc = subprocess.run(["psql", "-X", "-q", "-d", db, "-v", "ON_ERROR_STOP=1", "-f", "-"], input="\n".join(script),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode == 0:
        return None
    err = (proc.stderr or proc.stdout).strip().splitlines()
    # NULL arguments can make an otherwise valid statement fail at plan time (e.g. LIMIT NULL is fine, but casts of NULL may not be).
    return next((line for line in err if "ERROR" in line), err[-1] if err else "unknown error")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sadqah")
    ap.add_argument("paths", nargs="*", default=[str(Path(__file__).resolve().parents[1] / "app")])
    args = ap.parse_args()

    files = sorted(p for root in args.paths for p in ([Path(root)] if Path(root).is_file() else Path(root).rglob("*.py")))
    total = failed = 0
    for path in files:
        queries, warnings = collect(path)
        for w in warnings:
            print("WARN ", w)
        for q in queries:
            total += 1
            problem = check(q, args.db)
            if problem:
                failed += 1
                print(f"FAIL {q.path}:{q.line} [{q.role or 'role unknown'}] {problem}\n     {' '.join(q.sql.split())[:160]}")
    print(f"\n{total} statements checked, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
