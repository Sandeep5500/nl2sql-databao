PROJECT = "nl2sql-moe-dbt"

"""Replay every query from the bq_v2 run through the new guards.

Two questions, and the second matters more than the first:

  How many of the queries that actually failed would now be refused for free,
  before BigQuery is asked?

  How many queries that SUCCEEDED would the guards wrongly refuse? A guard with
  false positives costs accuracy silently, so this number has to be zero.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.bigquery_db import BigQueryDatabase  # noqa: E402

G = BigQueryDatabase


class Probe:
    """Just the guards, with a fixed namespace set -- no client, no catalog I/O."""

    def __init__(self, namespaces):
        self._ns = sorted(namespaces)
        self.display_name = "probe"
        # the real billing project, so the own-project exemption behaves as it will
        # in the run
        self.cfg = type("C", (), {"project": PROJECT})()

        class _Cat:
            namespaces = self._ns

            @staticmethod
            def project_for(ds):
                for n in self_ns_closure:
                    proj, _, d = n.rpartition(".")
                    if proj and d.lower() == ds.lower():
                        return proj
                return None

        self_ns_closure = self._ns
        self.catalog = _Cat()

    _INFO_SCHEMA = G._INFO_SCHEMA
    _CATALOG_HINT = G._CATALOG_HINT
    _QUALIFIED_REF = G._QUALIFIED_REF
    _known_namespaces = G._known_namespaces
    _reject_out_of_scope = G._reject_out_of_scope
    _reject_bare_information_schema = G._reject_bare_information_schema

    def judge(self, sql):
        if not re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.S).strip():
            return "empty_sql"
        try:
            self._reject_bare_information_schema(sql)
        except ValueError:
            return "information_schema"
        try:
            self._reject_out_of_scope(sql)
        except ValueError:
            return "out_of_scope"
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_dir", type=Path)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--project", default="nl2sql-moe-dbt",
                    help="the billing project, whose own INFORMATION_SCHEMA is allowed")
    args = ap.parse_args()
    global PROJECT
    PROJECT = args.project
    run = {r["instance_id"]: r
           for r in csv.DictReader(open(args.run, newline="", encoding="utf-8"))}
    # the namespaces each instance's database actually had, recovered from the
    # successful queries in its own trace: anything a query read without error is
    # by definition in scope
    ns_by_inst = {}
    queries = []
    for p in sorted(args.trace_dir.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        iid = p.stem
        ok_ns = set()
        qs = []
        for e in t.get("trace", []):
            if e.get("tool") != "run_sql_query":
                continue
            sql = str((e.get("args") or {}).get("sql", ""))
            res = str(e.get("result") or "")
            failed = res.lstrip().upper().startswith("ERROR")
            qs.append((sql, res, failed))
            if not failed:
                for m in re.finditer(r"`([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)\.", sql):
                    ok_ns.add(m.group(1))
        ns_by_inst[iid] = ok_ns
        queries.append((iid, qs))

    caught = Counter()
    false_pos = []
    n_ok = n_failed = 0
    caught_insts = {"information_schema": set(), "out_of_scope": set(),
                    "empty_sql": set()}
    for iid, qs in queries:
        ns = ns_by_inst[iid]
        if not ns:
            continue            # no successful query: cannot infer scope, skip
        probe = Probe(ns)
        for sql, res, failed in qs:
            verdict = probe.judge(sql)
            if failed:
                n_failed += 1
                if verdict:
                    caught[verdict] += 1
                    caught_insts[verdict].add(iid)
            else:
                n_ok += 1
                if verdict:
                    false_pos.append((iid, verdict, sql[:110]))

    print(f"queries replayed: {n_ok} succeeded, {n_failed} failed\n")
    print("failed queries the guards would refuse for free:")
    for k, v in caught.most_common():
        print(f"  {v:4d} queries across {len(caught_insts[k]):3d} instances  {k}")
    print(f"  {sum(caught.values()):4d} total "
          f"({100 * sum(caught.values()) / max(n_failed, 1):.1f}% of all failures)")

    print(f"\nFALSE POSITIVES (successful queries the guards would have refused): "
          f"{len(false_pos)}")
    for iid, v, sql in false_pos[:15]:
        print(f"  {iid}  {v}  {sql}")
    if not false_pos:
        print("  none -- no query that worked would now be refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
