#!/usr/bin/env python3
"""Assert the duckdb_sqlite system prompt matches the team's, byte for byte.

The local SQLite lane is the shared baseline, so a prompt that drifts by one
character silently invalidates every comparison against it. The dialect refactor
(prompts.DIALECTS) is exactly the kind of change that could drift, and so is a
placeholder added for one backend's benefit.

Two modes:

    # against a git ref -- the real check, and it tracks the team as they move
    python scripts/check_prompt_parity.py --ref origin/main

    # against a frozen snapshot, for bisecting
    python scripts/check_prompt_parity.py --write baseline_prompts.json
    python scripts/check_prompt_parity.py --check baseline_prompts.json

The frozen `baseline_prompts.json` was cut before the dialect refactor, against the
September prompt. The team has since reduced the pre-submit checklist from eight
bullets to two (49cca7d, dfcb1bf, 130800a), which was part of their 47.4% -> 51.3%
move, so that file is no longer the right target and --ref is. Keep it for bisecting
only.
"""

import argparse
import difflib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nl2sql.prompts as local_prompts  # noqa: E402

# the combinations the runner can actually produce. find_value is always available on
# the local lane (scanning a SQLite table is free) and never on BigQuery, so both
# values of it are rendered to keep the placeholder honest.
CASES = {"search_doc": (True, True, True), "search_nodoc": (True, False, True),
         "full_doc": (False, True, True), "full_nodoc": (False, False, True),
         "full_nodoc_nofind": (False, False, False)}


def render(mod, has_search: bool, has_doc: bool, has_find: bool = True) -> str:
    """Render mod's duckdb_sqlite system prompt. Tolerates older/newer module
    versions: placeholders a given revision does not have are simply not passed."""
    extra = {}
    dialects = getattr(mod, "DIALECTS", None)
    if dialects is not None:            # absent before the dialect refactor
        d = dialects["duckdb_sqlite"]
        extra = {"dialect_header": d.header, "dialect_rules": d.sql_rules}
    if "{value_hint}" in mod.SYSTEM_PROMPT:
        extra["value_hint"] = mod.VALUE_HINT_FIND if has_find else mod.VALUE_HINT_PLAIN
    if "{value_hint_loop}" in mod.SYSTEM_PROMPT:
        extra["value_hint_loop"] = (mod.VALUE_HINT_LOOP_FIND if has_find
                                    else mod.VALUE_HINT_LOOP_PLAIN)
    return mod.SYSTEM_PROMPT.format(
        search_hint=(mod.SEARCH_HINT_SEARCH if has_search else mod.SEARCH_HINT_FULL),
        doc_hint=mod.DOC_HINT if has_doc else "",
        max_steps=30, db_name="BASELINE_DB", question="BASELINE_QUESTION?",
        extra_context="BASELINE_EXTRA", **extra)


def load_ref(ref: str):
    """Import nl2sql/prompts.py as it exists at a git ref, without checking it out."""
    src = subprocess.run(
        ["git", "show", f"{ref}:nl2sql-v2/src/nl2sql/prompts.py"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=Path(__file__).resolve().parents[2])
    if src.returncode:
        raise SystemExit(f"could not read prompts.py at {ref}: {src.stderr.strip()}")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ref_prompts.py"
        path.write_text(src.stdout, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("ref_prompts", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def report(rendered: dict, baseline: dict, label: str) -> int:
    bad = []
    for name in sorted(set(rendered) | set(baseline)):
        want, got = baseline.get(name), rendered.get(name)
        if want is None:
            print(f"  --   {name}: not in {label}; skipped")
            continue
        if got is None:
            print(f"  FAIL {name}: missing locally")
            bad.append(name)
        elif want == got:
            print(f"  ok   {name}: byte-identical ({len(got)} chars)")
        else:
            bad.append(name)
            print(f"  FAIL {name}: differs")
            diff = difflib.unified_diff(want.splitlines(), got.splitlines(),
                                        f"{label}/{name}", f"local/{name}",
                                        lineterm="", n=1)
            for line in list(diff)[:40]:
                print("       " + line)
    if bad:
        print(f"\n{len(bad)} prompt(s) differ from {label}: {', '.join(bad)}")
        return 1
    print(f"\nthe duckdb_sqlite prompt matches {label} exactly")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", metavar="PATH")
    g.add_argument("--check", metavar="PATH", nargs="?",
                   const=str(Path(__file__).with_name("baseline_prompts.json")))
    g.add_argument("--ref", metavar="GITREF",
                   help="compare against prompts.py at this git ref "
                        "(e.g. origin/main)")
    args = ap.parse_args()

    rendered = {k: render(local_prompts, *v) for k, v in CASES.items()}

    if args.write:
        Path(args.write).write_text(json.dumps(rendered, indent=1), encoding="utf-8")
        print(f"wrote {len(rendered)} baseline prompts to {args.write}")
        return 0

    if args.ref:
        ref_mod = load_ref(args.ref)
        # the ref has no value_hint placeholder, so its render is the has_find=True
        # text by construction; only those cases are comparable.
        baseline = {k: render(ref_mod, *v) for k, v in CASES.items() if v[2]}
        print(f"duckdb_sqlite prompt vs {args.ref}:")
        return report(rendered, baseline, args.ref)

    path = Path(args.check)
    if not path.exists():
        raise SystemExit(f"no baseline at {path}; write one first")
    print(f"duckdb_sqlite prompt vs {path.name}:")
    return report(rendered, json.loads(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    raise SystemExit(main())
