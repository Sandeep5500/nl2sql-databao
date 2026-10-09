"""A writable copy of one Spider 2.0-DBT project, isolated from the pristine tree.

Two hazards this encapsulates, both of which produce failures that look like model
errors if you leave them to convention:

1. The staged copy's profiles.yml can still point at the ORIGINAL .duckdb file
   (dbt-duckdb paths are often absolute, or relative to somewhere outside the
   project). Then `dbt build` writes into Spider2/spider2-dbt/examples/ and corrupts
   the benchmark for every later run. So staging rewrites the profile to a path
   inside the workspace, copying the source database in if it lived elsewhere.

2. DuckDB allows a single writer. If an inspection connection is open when dbt
   starts, dbt fails with a lock error that reads like a broken model. So the
   connection is owned here and `close_duckdb()` is called before every dbt
   invocation, with a lazy reopen afterwards.
"""

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .db import DuckDBFile


@dataclass
class DbtWorkspace:
    instance_id: str
    source_dir: Path            # Spider2/spider2-dbt/examples/<iid> -- never written
    root: Path                  # the writable copy
    duckdb_path: Path
    profile_name: str = ""
    target: str = ""
    _db: DuckDBFile | None = field(default=None, repr=False)
    _source_fingerprint: str = ""

    # ── staging ───────────────────────────────────────────────────────────
    @classmethod
    def stage(cls, instance_id: str, source_dir: Path, scratch_dir: Path,
              run_tag: str = "run") -> "DbtWorkspace":
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            raise FileNotFoundError(f"no dbt project at {source_dir}")
        root = Path(scratch_dir) / run_tag / instance_id
        if root.exists():
            shutil.rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, root)

        ws = cls(instance_id=instance_id, source_dir=source_dir, root=root,
                 duckdb_path=root / "spider2.duckdb")
        ws._source_fingerprint = ws.fingerprint_source()
        ws._localize_profile()
        return ws

    def _localize_profile(self) -> None:
        """Point the staged profiles.yml at a database inside the workspace."""
        prof_path = self.root / "profiles.yml"
        if not prof_path.exists():
            raise FileNotFoundError(
                f"{self.instance_id}: no profiles.yml in the staged project; "
                f"cannot tell dbt where its database is")
        prof = yaml.safe_load(prof_path.read_text(encoding="utf-8")) or {}

        # profiles.yml is {profile_name: {target: ..., outputs: {name: {...}}}}
        names = [k for k in prof if isinstance(prof[k], dict) and "outputs" in prof[k]]
        if not names:
            raise ValueError(f"{self.instance_id}: profiles.yml has no profile with "
                             f"outputs: {sorted(prof)}")
        self.profile_name = names[0]
        block = prof[self.profile_name]
        outputs = block.get("outputs") or {}
        self.target = block.get("target") or next(iter(outputs))
        out = outputs.get(self.target)
        if not isinstance(out, dict):
            raise ValueError(f"{self.instance_id}: profiles.yml target "
                             f"{self.target!r} has no output block")

        old = out.get("path")
        resolved = None
        if old and str(old) not in (":memory:",):
            p = Path(str(old))
            for base in (self.root, self.source_dir, Path.cwd()):
                cand = p if p.is_absolute() else (base / p)
                if cand.exists():
                    resolved = cand.resolve()
                    break
            if resolved is None and p.is_absolute():
                resolved = p

        if resolved and resolved.exists():
            inside = self.root.resolve() in resolved.parents or \
                resolved.parent == self.root.resolve()
            if inside:
                # copytree already brought it along; just use it where it landed
                self.duckdb_path = resolved
            else:
                # lived outside the project (a shared database dir): copy it in, so
                # dbt's writes cannot reach the original
                shutil.copy2(resolved, self.duckdb_path)
        # else: no source database yet -- dbt will create self.duckdb_path

        # always rewrite, so the stored path is unambiguous and inside the workspace
        out["path"] = str(self.duckdb_path)
        prof_path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")

    # ── isolation assertion ───────────────────────────────────────────────
    def fingerprint_source(self) -> str:
        """sha256 over (relative path, size) of the pristine tree. Compared at
        teardown: a mismatch means something escaped the sandbox, and we want that
        to be an assertion rather than a hope."""
        h = hashlib.sha256()
        for p in sorted(self.source_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(self.source_dir).as_posix()
                h.update(rel.encode("utf-8"))
                h.update(str(p.stat().st_size).encode("utf-8"))
        return h.hexdigest()

    def assert_source_untouched(self) -> None:
        now = self.fingerprint_source()
        if now != self._source_fingerprint:
            raise RuntimeError(
                f"{self.instance_id}: the pristine project at {self.source_dir} "
                f"CHANGED during the episode (fingerprint {self._source_fingerprint} "
                f"-> {now}). Stop the run: later instances are now contaminated.")

    # ── the DuckDB handle, owned here because of the single-writer rule ───
    def duckdb(self) -> DuckDBFile:
        """Lazily open a read-only handle. Raises if dbt has not produced the
        database yet, which is an actionable message for the agent."""
        if self._db is None:
            if not self.duckdb_path.exists():
                raise FileNotFoundError(
                    f"the project database does not exist yet at "
                    f"{self.duckdb_path.name} - run dbt first (e.g. run_dbt('build'))")
            self._db = DuckDBFile(self.duckdb_path, read_only=True)
        return self._db

    def close_duckdb(self) -> None:
        """Must be called before every dbt invocation: DuckDB permits one writer,
        and an open reader makes `dbt build` fail with a lock error."""
        if self._db is not None:
            try:
                self._db.close()
            finally:
                self._db = None

    # ── context for the system prompt ─────────────────────────────────────
    def project_overview(self, max_chars: int = 6_000) -> str:
        """What the agent needs before its first tool call: the project layout and
        its own dbt_project.yml. Deliberately a map, not the contents of every model
        -- read_file exists for that, and dumping the project would eat the history
        budget before the first dbt run."""
        skip = {"dbt_packages", "target", "logs", ".git"}
        lines = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if rel.parts and rel.parts[0] in skip:
                continue
            if p.is_file():
                lines.append(f"  {rel.as_posix()}  ({p.stat().st_size}B)")
        tree = "\n".join(lines)
        if len(tree) > max_chars:
            kept = []
            used = 0
            for ln in lines:
                if used + len(ln) + 1 > max_chars:
                    break
                kept.append(ln)
                used += len(ln) + 1
            tree = ("\n".join(kept)
                    + f"\n  [{len(lines) - len(kept)} more files - use list_files]")

        parts = [f"\nYou are completing the dbt project '{self.instance_id}'.",
                 f"Project root (all paths are relative to it):\n{tree}"]
        cfg = self.root / "dbt_project.yml"
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8")
            if len(text) > 2_000:
                text = text[:2_000] + "\n[truncated - read_file('dbt_project.yml')]"
            parts.append(f"dbt_project.yml:\n{text}")
        parts.append(
            f"dbt profile '{self.profile_name}' target '{self.target}' writes to "
            f"{self.duckdb_path.name} (DuckDB). The vendored dbt_packages/ are "
            f"available; do not edit them.")
        return "\n\n".join(parts)
