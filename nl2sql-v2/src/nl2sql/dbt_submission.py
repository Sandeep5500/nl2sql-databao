"""Write a Spider 2.0-DBT submission folder, in the format their evaluator reads.

Verified against spider2-dbt/evaluation_suite/{evaluate.py,eval_utils.py,gold}:

  * the gold config is ONE file, gold/spider2_eval.jsonl, with entries
    {instance_id, evaluation: {func, parameters}}  (evaluation may be a list)
  * all 68 scored instances use func "duckdb_match"
  * our metadata lines are {instance_id, answer_type, answer_or_path} -- the field is
    answer_or_path, not "answer"
  * for answer_type "file" they open result_dir/<instance_id>/<answer_or_path>, so
    answer_or_path is a BARE FILENAME, not a path containing the instance id
  * duckdb_match(result_db, gold_db, condition_tabs, condition_cols, ignore_orders)
    opens our DuckDB file and reads each condition_tabs table out of it; a missing
    table scores 0, and extra tables are ignored

So for dbt the deliverable is the project's whole DuckDB database, not a CSV: the
agent's job is to make `dbt build` materialise the right tables, and we hand over the
database it produced. The condition_tabs names live in the gold and are deliberately
NOT shown to the agent.

Each instance is flushed as it finishes, so a killed run still leaves a scorable
partial submission -- the same discipline as run_benchmark.py's per-row flush.
"""

import json
import shutil
from pathlib import Path

import pandas as pd

GOLD_JSONL = "spider2_eval.jsonl"      # asserted by their evaluate.py
SCALAR_FUNCS = ("string_match", "number_match")


def load_gold_config(gold_dir: Path) -> dict:
    """instance_id -> gold entry, from gold/spider2_eval.jsonl.

    Older/other Spider2 tracks name this file differently, so a couple of aliases are
    accepted; {} means "no gold here", which the census reports as a blocker rather
    than something to paper over.
    """
    gold_dir = Path(gold_dir)
    if not gold_dir.exists():
        return {}
    for name in (GOLD_JSONL, "spider2dbt_eval.jsonl", "gold.jsonl", "eval.jsonl"):
        p = gold_dir / name
        if not p.exists():
            continue
        out = {}
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    if row.get("instance_id"):
                        out[row["instance_id"]] = row
        if out:
            return out
    return {}


def gold_funcs(gold_entry: dict | None) -> list[str]:
    """The match function names an entry declares (it may carry a list of them)."""
    if not gold_entry:
        return []
    ev = gold_entry.get("evaluation")
    if ev is None:
        return []
    evs = ev if isinstance(ev, list) else [ev]
    return [str(e.get("func")) for e in evs if isinstance(e, dict) and e.get("func")]


def gold_db_name(gold_entry: dict | None) -> str | None:
    """The gold database's filename, reused for ours so a pair is easy to eyeball."""
    if not gold_entry:
        return None
    ev = gold_entry.get("evaluation")
    evs = ev if isinstance(ev, list) else [ev]
    for e in evs:
        if isinstance(e, dict) and e.get("func") == "duckdb_match":
            g = (e.get("parameters") or {}).get("gold")
            if isinstance(g, str) and g.endswith(".duckdb"):
                return Path(g).name
    return None


def scalar_of(df: pd.DataFrame) -> str:
    value = df.iloc[0, 0]
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class DbtSubmission:
    """Accumulates a submission folder, flushing after every instance."""

    def __init__(self, out_dir: Path, gold_dir: Path | None = None):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.out_dir / "results_metadata.jsonl"
        self.gold = load_gold_config(gold_dir) if gold_dir else {}
        self._written: dict[str, dict] = {}
        if self.metadata_path.exists():      # resume: keep what is already there
            with open(self.metadata_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        self._written[row["instance_id"]] = row

    def done_ids(self) -> set:
        return set(self._written)

    def record(self, instance_id: str, df: pd.DataFrame | None,
               description: str = "", duckdb_path: Path | None = None) -> dict:
        """Write this instance's artifact and its metadata line.

        `duckdb_path` is the project's database. For duckdb_match instances (all of
        spider2-dbt) that IS the answer, whether or not the agent also submitted a
        query result -- so a run whose agent forgot to call submit_result still hands
        over the work dbt did.
        """
        entry = self.gold.get(instance_id)
        funcs = gold_funcs(entry)
        inst_dir = self.out_dir / instance_id
        inst_dir.mkdir(parents=True, exist_ok=True)

        want_db = ("duckdb_match" in funcs) or (not funcs and duckdb_path
                                                and Path(duckdb_path).exists())
        have_db = duckdb_path is not None and Path(duckdb_path).exists()

        if want_db and have_db:
            name = gold_db_name(entry) or "result.duckdb"
            shutil.copy2(duckdb_path, inst_dir / name)
            row = {"instance_id": instance_id, "answer_type": "file",
                   "answer_or_path": name,
                   "note": "project database after dbt build"}
        elif want_db and not have_db:
            row = {"instance_id": instance_id, "answer_type": "file",
                   "answer_or_path": "result.duckdb",
                   "note": "no project database was produced (dbt never built)"}
        elif any(f in SCALAR_FUNCS for f in funcs) and df is not None and len(df):
            row = {"instance_id": instance_id, "answer_type": "answer",
                   "answer_or_path": scalar_of(df)}
        elif df is not None:
            df.to_csv(inst_dir / "result.csv", index=False)
            row = {"instance_id": instance_id, "answer_type": "file",
                   "answer_or_path": "result.csv",
                   "rows": int(df.shape[0]), "cols": int(df.shape[1])}
        else:
            row = {"instance_id": instance_id, "answer_type": "answer",
                   "answer_or_path": "", "note": "no result produced"}

        if description:
            row["description"] = description
        self._written[instance_id] = row
        self._flush()
        return row

    def _flush(self) -> None:
        """Rewrite the whole metadata file: it is one short line per instance, and
        rewriting keeps it valid when a resumed run revisits an instance.

        Only the keys their evaluator reads go in the jsonl their evaluator parses --
        extras are harmless (it merges gold and result dicts) but kept minimal.
        """
        tmp = self.metadata_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for iid in sorted(self._written):
                f.write(json.dumps(self._written[iid]) + "\n")
        tmp.replace(self.metadata_path)


def resolve_gold_db(gold_dir: Path, instance_id: str,
                    configured: str | None) -> tuple[Path | None, bool]:
    """Locate an instance's gold database, tolerating filename drift.

    Their gold config and their archive disagree for a few instances -- e.g.
    xero_new001's entry names xero.duckdb but the archive ships xero_new.duckdb, and
    social_media001 names social_media_reporting__rollup_report.duckdb but ships
    social_media.duckdb. Their own evaluate.py joins the configured name blindly and
    scores those 0.

    When the configured name is absent but the instance's gold directory holds exactly
    one .duckdb, that file is unambiguously the gold, so use it and report that a
    repair happened -- the caller labels those rows so a repaired score is never
    mistaken for a clean one.

    Returns (path or None, repaired).
    """
    d = Path(gold_dir) / instance_id
    if configured:
        exact = d / configured
        if exact.exists():
            return exact, False
    if not d.is_dir():
        return None, False
    found = sorted(d.glob("*.duckdb"))
    if len(found) == 1:
        return found[0], True
    return None, False
