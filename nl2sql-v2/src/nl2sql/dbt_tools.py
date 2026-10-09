"""Tools for the Spider 2.0-DBT lane: file editing plus a dbt runner.

DbtToolSession satisfies the same duck contract as ToolSession (dispatch,
get_submission, query_results, search/doc_text/draft, search_calls), so
agent.run_episode is reused verbatim -- including its memory compaction and its
step-cap fallback that picks the best-validated result cluster.

The submit path deliberately stays submit_result(query_id): the agent builds models,
runs dbt, then SELECTs the answer out of the project database, and that DataFrame is
the deliverable. Whether it is written as a CSV, a scalar or a .duckdb is decided
later by dbt_submission, which can read the gold config -- so the episode does not
need to know.
"""

import difflib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import pandas as pd

from pathlib import Path as pathlib_Path

from .config import AgentConfig
from .dbt_workspace import DbtWorkspace
from .prompts import DBT_SYSTEM_PROMPT, DIALECTS

# Writable paths. An allow-list, not a deny-list: anything not named here stays
# read-only. profiles.yml is excluded on purpose -- it holds the database path, and
# an agent breaking it turns every later failure into an unreadable environment error.
WRITABLE_DIRS = ("models/", "macros/", "seeds/", "analyses/", "snapshots/", "tests/")
WRITABLE_FILES = ("dbt_project.yml",)

# Listing these would bury the project map; read_file can still reach them.
HIDDEN_DIRS = {"dbt_packages", "target", "logs", ".git", ".venv"}

DBT_COMMANDS = {"run", "build", "test", "compile", "seed", "deps", "ls", "debug",
                "snapshot", "parse"}

# dbt colours its output; the escape codes are pure noise in a prompt
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[[0-9;]*m")

_ERROR_LINE = re.compile(
    r"(Compilation Error|Database Error|Runtime Error|Parsing Error|"
    r"Dependency Error|FAIL \d+|ERROR|error)", re.IGNORECASE)


def dbt_executable() -> str | None:
    """`dbt` on PATH, else next to the running interpreter.

    `uv run python ...` does not always put the venv's bin/Scripts dir on
    PATH, so a PATH-only lookup would make the lane look uninstalled when it
    is merely not exported."""
    found = shutil.which("dbt")
    if found:
        return found
    bindir = pathlib_Path(sys.executable).parent
    for name in ("dbt.exe", "dbt"):
        cand = bindir / name
        if cand.exists():
            return str(cand)
    return None


def build_dbt_tool_schemas(cfg: AgentConfig) -> list[dict]:
    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props,
                           "required": required}}}

    writable = ", ".join(WRITABLE_DIRS + WRITABLE_FILES)
    return [
        fn("list_files",
           "List files in the dbt project. Start here to see the models that already "
           "exist and how they are organised.",
           {"glob": {"type": "string",
                     "description": "Optional glob, e.g. 'models/**/*.sql'. "
                                    "Default: the whole project."}},
           []),
        fn("read_file",
           "Read one project file. Read the existing models before writing new ones: "
           "they establish the naming, the ref() wiring and the SQL style to match.",
           {"path": {"type": "string", "description": "Path relative to the project root."}},
           ["path"]),
        fn("write_file",
           f"Create or overwrite a project file. Writable: {writable}. Returns a diff "
           f"of what changed.",
           {"path": {"type": "string"},
            "content": {"type": "string", "description": "The complete new file contents."}},
           ["path", "content"]),
        fn("run_dbt",
           "Run a dbt command in the project (build/run/test/compile/seed/deps/ls/"
           "debug). Use build to materialise your models, then fix whatever it "
           "reports. Output is condensed to the failures plus a tail.",
           {"command": {"type": "string",
                        "description": f"One of: {', '.join(sorted(DBT_COMMANDS))}"},
            "select": {"type": "string",
                       "description": "Optional dbt --select, e.g. a model name."}},
           ["command"]),
        fn("run_sql_query",
           "Run one DuckDB SELECT against the project database to inspect sources or "
           "check what your models produced. Returns a CSV preview plus a query_id "
           f"(full result up to {cfg.result_rows_max} rows is stored for submission).",
           {"sql": {"type": "string", "description": "A single DuckDB SELECT statement."},
            "preview_rows": {"type": "integer",
                             "description": f"Rows to show (1-{cfg.preview_rows_max})."}},
           ["sql"]),
        fn("list_tables", "List tables currently in the project database.", {}, []),
        fn("describe_table",
           "Columns, types, row counts and sample rows for one table in the project "
           "database. Use it on the sources before modelling them.",
           {"table": {"type": "string"}}, ["table"]),
        fn("submit_result",
           "Submit the stored result of a previous run_sql_query as the final answer "
           "to the instruction. Must be your only tool call in the message.",
           {"query_id": {"type": "string"},
            "result_description": {"type": "string",
                                   "description": "One sentence on what the answer is."}},
           ["query_id", "result_description"]),
    ]


@dataclass
class DbtToolSession:
    ws: DbtWorkspace
    cfg: AgentConfig
    # present so run_episode's checks (`session.search is not None`, etc.) work
    search: object | None = None
    doc_text: str | None = None
    draft: object | None = None
    query_results: dict = field(default_factory=dict)
    search_calls: int = 0
    draft_calls: int = 0
    dbt_calls: int = 0
    write_calls: int = 0
    dbt_build_ok: bool = False       # did any build/run ever exit 0
    _query_counter: int = 0

    # ── what run_episode reads off the session ────────────────────────────
    @property
    def db(self):
        """run_episode only needs display_name/dialect from this at prompt time;
        the real connection is opened lazily by the tools that query."""
        return _ProjectHandle(self.ws)

    def tool_schemas(self) -> list[dict]:
        return build_dbt_tool_schemas(self.cfg)

    def system_prompt(self, question: str, cfg: AgentConfig,
                      extra_context: str = "") -> str:
        """run_episode calls this instead of SYSTEM_PROMPT when present."""
        return DBT_SYSTEM_PROMPT.format(
            dialect_rules=DIALECTS["duckdb"].sql_rules,
            max_steps=cfg.max_steps, question=question,
            extra_context=extra_context)

    def get_submission(self, query_id: str):
        return self.query_results.get(query_id)

    # ── dispatch ──────────────────────────────────────────────────────────
    def dispatch(self, name: str, args: dict) -> str:
        try:
            return self._dispatch(name, args)
        except Exception as e:      # tool errors go back to the model, not up
            return f"ERROR: {type(e).__name__}: {e}"

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "list_files":
            return self._list_files(args.get("glob") or "**/*")
        if name == "read_file":
            return self._read_file(args["path"])
        if name == "write_file":
            return self._write_file(args["path"], args.get("content", ""))
        if name == "run_dbt":
            return self._run_dbt(args["command"], args.get("select"))
        if name == "run_sql_query":
            return self._run_sql(args["sql"], args.get("preview_rows"))
        if name == "list_tables":
            return "\n".join(self.ws.duckdb().list_tables()) or "(no tables yet)"
        if name == "describe_table":
            return self.ws.duckdb().describe_table(args["table"])
        raise ValueError(f"unknown tool {name!r}")

    # ── path safety ───────────────────────────────────────────────────────
    def _safe(self, rel_path: str):
        root = self.ws.root.resolve()
        p = (root / str(rel_path)).resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"path {rel_path!r} escapes the project directory")
        return p

    @staticmethod
    def _is_writable(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("./")
        return rel in WRITABLE_FILES or rel.startswith(WRITABLE_DIRS)

    # ── file tools ────────────────────────────────────────────────────────
    def _list_files(self, pattern: str) -> str:
        root = self.ws.root
        out = []
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root)
            if rel.parts and rel.parts[0] in HIDDEN_DIRS:
                continue
            if p.is_file():
                out.append(f"{rel.as_posix()}  ({p.stat().st_size}B)")
        if not out:
            return f"no files match {pattern!r} (vendored packages are hidden)"
        text = "\n".join(out)
        if len(text) > self.cfg.max_tool_result_chars:
            text = (text[: self.cfg.max_tool_result_chars]
                    + "\n[truncated - narrow the glob]")
        return text

    def _read_file(self, rel_path: str) -> str:
        p = self._safe(rel_path)
        if not p.is_file():
            near = difflib.get_close_matches(
                str(rel_path), [str(q.relative_to(self.ws.root).as_posix())
                                for q in self.ws.root.rglob("*") if q.is_file()],
                n=5, cutoff=0.5)
            hint = (" Did you mean: " + ", ".join(near) + ".") if near else ""
            raise FileNotFoundError(f"no such file {rel_path!r}.{hint}")
        text = p.read_text(encoding="utf-8", errors="replace")
        cap = self.cfg.max_tool_result_chars
        if len(text) > cap:
            head, tail = text[: int(cap * 0.7)], text[-int(cap * 0.25):]
            text = (head + f"\n[... {len(text) - len(head) - len(tail)} chars "
                           f"elided ...]\n" + tail)
        return text

    def _write_file(self, rel_path: str, content: str) -> str:
        if not self._is_writable(str(rel_path)):
            raise PermissionError(
                f"{rel_path!r} is not writable. You may write: "
                f"{', '.join(WRITABLE_DIRS + WRITABLE_FILES)}. "
                f"profiles.yml and dbt_packages/ are fixed.")
        p = self._safe(rel_path)
        before = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.write_calls += 1
        diff = list(difflib.unified_diff(
            before.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}", n=1))
        verb = "updated" if before else "created"
        if not diff:
            return f"{rel_path}: unchanged (content identical)"
        shown = "".join(diff)
        if len(shown) > 2_000:
            shown = shown[:2_000] + "\n[diff truncated]"
        return f"{verb} {rel_path} ({len(content)} chars)\n{shown}"

    # ── dbt ───────────────────────────────────────────────────────────────
    def _run_dbt(self, command: str, select: str | None) -> str:
        command = str(command).strip().split()[0] if command else ""
        if command not in DBT_COMMANDS:
            raise ValueError(f"dbt command {command!r} is not allowed. "
                             f"Use one of: {', '.join(sorted(DBT_COMMANDS))}")
        # DuckDB permits one writer: our reader must be gone before dbt starts
        self.ws.close_duckdb()
        exe = dbt_executable()
        if exe is None:
            raise RuntimeError(
                "the `dbt` executable was not found on PATH or beside "
                f"{sys.executable}; install the dbt extra "
                "(uv sync --extra dbt)")
        argv = [exe, command, "--project-dir", str(self.ws.root),
                "--profiles-dir", str(self.ws.root)]
        if select:
            argv += ["--select", str(select)]
        self.dbt_calls += 1
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  cwd=str(self.ws.root),
                                  timeout=self.cfg.dbt_timeout_s)
        except FileNotFoundError:
            raise RuntimeError(f"could not execute {exe}; reinstall the dbt extra")
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"dbt {command} exceeded "
                               f"{self.cfg.dbt_timeout_s}s and was killed")
        if proc.returncode == 0 and command in ("build", "run"):
            self.dbt_build_ok = True
        return self._condense_dbt(command, proc.returncode,
                                  (proc.stdout or "") + (proc.stderr or ""))

    def _condense_dbt(self, command: str, code: int, output: str) -> str:
        """Raw `dbt build` output is 100+ lines of banner and timing. Returned whole
        it would exhaust history_char_budget in a few calls and trigger memory
        compaction over noise, so keep the failures and a tail."""
        lines = [_ANSI.sub("", ln).rstrip() for ln in output.splitlines()]
        failures, seen = [], set()
        for i, ln in enumerate(lines):
            if _ERROR_LINE.search(ln):
                block = " ".join(x.strip() for x in lines[i:i + 4] if x.strip())
                key = block[:160]
                if key not in seen:
                    seen.add(key)
                    failures.append(block[:400])
        head = [f"exit_code={code}"]
        if failures:
            head.append(f"FAILURES / ERRORS ({len(failures)} distinct):")
            head += ["  " + f for f in failures[:12]]
        elif code == 0:
            head.append(f"dbt {command} succeeded")
        tail = [ln for ln in lines if ln.strip()][-20:]
        head.append("tail:")
        head += ["  " + ln for ln in tail]
        text = "\n".join(head)
        cap = self.cfg.max_tool_result_chars
        return text if len(text) <= cap else text[:cap] + "\n[output truncated]"

    # ── SQL against the project database ──────────────────────────────────
    def _run_sql(self, sql: str, preview_rows) -> str:
        preview = min(int(preview_rows or self.cfg.preview_rows_default),
                      self.cfg.preview_rows_max)
        db = self.ws.duckdb()
        df, csv = db.query_preview(sql, preview, self.cfg.result_rows_max,
                                   self.cfg.cell_char_limit)
        self._query_counter += 1
        qid = f"q{self._query_counter}"
        self.query_results[qid] = (sql, df)
        return f"query_id='{qid}'\n{csv}"


@dataclass
class _ProjectHandle:
    """What run_episode needs from `session.db` for the system prompt."""
    ws: DbtWorkspace
    dialect: str = "duckdb"

    @property
    def display_name(self) -> str:
        return f"{self.ws.instance_id} (dbt project, DuckDB)"
