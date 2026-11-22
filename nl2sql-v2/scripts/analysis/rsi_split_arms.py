"""Split a multi-arm proposal into one directory per arm, and validate each.

`rsi_propose.py --n-proposals N` returns N arms in one response, each with its
own `# ARM k:` header and its own ```diff block. Each arm must then run in its
own isolated copy of the code, so each needs its own patch file and its own
validation verdict -- an arm whose diff does not apply must be dropped or
repaired on its own, without touching the others.

Independence is checked here, not assumed: if two arms modify the same file AND
the same hunk region, their effects cannot be separated afterwards, so the
overlap is reported and the pair is flagged.

Usage:
    python rsi_split_arms.py --proposal rounds/r2/proposal.md \
        --out-dir rounds/r2 --repo-root nl2sql-v2
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rsi_propose import validate_patch

ARM_RE = re.compile(r"^#\s*ARM\s*(\d+)\s*:\s*(.+?)\s*$", re.M)
DIFF_RE = re.compile(r"```diff\s*\n(.*?)```", re.S)


def split_arms(text):
    """Return [(index, name, body)] for each `# ARM k: name` section."""
    marks = list(ARM_RE.finditer(text))
    if not marks:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(m.group(1)), m.group(2).strip(), text[m.end():end]))
    return out


def touched_regions(patch):
    """{file: [(start, end)]} from the hunk headers, to detect real overlap."""
    regions = defaultdict(list)
    cur = None
    for line in patch.splitlines():
        if line.startswith("+++ "):
            cur = line[4:].strip()
            if cur.startswith(("a/", "b/")):
                cur = cur[2:]
        elif line.startswith("@@") and cur:
            m = re.search(r"@@\s*-(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                length = int(m.group(2) or 1)
                regions[cur].append((start, start + length))
    return regions


def overlaps(ra, rb):
    """Do two arms touch the same lines of the same file?"""
    hits = []
    for f, spans_a in ra.items():
        for sa, ea in spans_a:
            for sb, eb in rb.get(f, []):
                if sa < eb and sb < ea:          # half-open interval overlap
                    hits.append(f"{f}:{sa}-{ea} vs {sb}-{eb}")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--repo-root", required=True,
                    help="nl2sql-v2 root, to verify each patch applies")
    a = ap.parse_args()

    text = Path(a.proposal).read_text()
    arms = split_arms(text)
    if not arms:
        sys.exit("no `# ARM k:` sections found -- was --n-proposals used?")

    out = Path(a.out_dir)
    summary, regions = [], {}
    for idx, name, body in arms:
        d = out / f"arm{idx}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "notes.md") in ()                      # no-op; keeps intent clear
        (d / "notes.md").write_text(f"# ARM {idx}: {name}\n{body}")

        diffs = DIFF_RE.findall(body)
        if not diffs:
            summary.append({"arm": idx, "name": name, "ok": False,
                            "problems": ["no ```diff block in this arm"]})
            continue
        if len(diffs) > 1:
            # more than one diff in a single arm defeats attribution
            summary.append({"arm": idx, "name": name, "ok": False,
                            "problems": [f"{len(diffs)} diff blocks; an arm must "
                                         f"carry exactly one"]})
            continue
        patch = diffs[0]
        (d / "arm.patch").write_text(patch)
        ok, problems = validate_patch(patch, a.repo_root)
        regions[idx] = touched_regions(patch)
        summary.append({"arm": idx, "name": name, "ok": ok, "problems": problems})

    # independence: same file AND same lines means the arms are not separable
    collisions = []
    ids = sorted(regions)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            hits = overlaps(regions[x], regions[y])
            if hits:
                collisions.append({"arms": [x, y], "where": hits})

    (out / "arms.json").write_text(json.dumps(
        {"arms": summary, "collisions": collisions}, indent=2))

    print(f"{len(arms)} arms parsed from {a.proposal}\n")
    for r in summary:
        mark = "OK  " if r["ok"] else "FAIL"
        print(f"  [{mark}] arm{r['arm']}: {r['name']}")
        for p in r["problems"]:
            print(f"         - {p}")
    if collisions:
        print("\n  !! arms touching the same lines -- NOT independent:")
        for c in collisions:
            print(f"     arms {c['arms']}: {'; '.join(c['where'])}")
    else:
        print("\n  independence: no two arms touch the same lines")
    runnable = [r["arm"] for r in summary if r["ok"]]
    print(f"\n  runnable arms: {runnable or 'none'}")


if __name__ == "__main__":
    main()
