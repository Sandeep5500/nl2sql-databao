"""Recompute unified-diff hunk header counts from the hunk bodies.

Models reliably get diff CONTENT right and hunk ARITHMETIC wrong. Across round 1
and round 2, four of six patches were rejected by patch(1) for header counts that
did not match their bodies -- `@@ -37,5 +38,63 @@` above 64 body lines, or
`@@ -68,2 +68,4 @@` above two context lines and no additions. When patch(1)
desyncs on such a hunk it then misreads the following `--- a/file` as content and
reports nonsense ("No file to patch").

This rewrites ONLY the four integers in each `@@` header, derived from the lines
beneath it:
    old_len = context + removed
    new_len = context + added
It never adds, removes or reorders a body line, so the change being measured is
still entirely the proposer's. A patch whose body is wrong stays wrong -- this
only stops a correct body from being thrown away over bookkeeping.

The start line numbers are left alone: those encode where the proposer meant the
change to go, and patch(1) can fuzz them, while it cannot fuzz a bad count.

An empty diff (no + and no - lines) is reported, not repaired: there is nothing
to fix and it must not run as a silent no-op arm.

Usage:
    python rsi_fix_hunks.py --patch rounds/r2/arm1/arm.patch [--in-place]
"""
import argparse
import re
import sys
from pathlib import Path

HUNK = re.compile(r"^@@\s*-(\d+)(?:,(\d+))?\s*\+(\d+)(?:,(\d+))?\s*@@(.*)$")


def fix(text):
    lines = text.splitlines()
    out, i, changes = [], 0, []
    while i < len(lines):
        line = lines[i]
        m = HUNK.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        old_start, _, new_start, _, tail = m.groups()
        # collect the body: everything until the next hunk or file header
        body, j = [], i + 1
        while j < len(lines):
            nxt = lines[j]
            if HUNK.match(nxt) or nxt.startswith(("--- ", "+++ ", "diff --git")):
                break
            body.append(nxt)
            j += 1

        # trailing blank lines belong to no hunk; patch(1) treats a bare "" as
        # an empty context line, which is a frequent source of off-by-one
        while body and body[-1].strip() == "":
            body.pop()

        ctx = sum(1 for b in body if b.startswith(" ") or b == "")
        add = sum(1 for b in body if b.startswith("+"))
        rem = sum(1 for b in body if b.startswith("-"))
        old_len, new_len = ctx + rem, ctx + add

        new_header = f"@@ -{old_start},{old_len} +{new_start},{new_len} @@{tail}"
        if new_header.split("@@")[1].strip() != line.split("@@")[1].strip():
            changes.append((line.strip(), new_header.strip()))
        out.append(new_header)
        out.extend(body)
        i = j
    return "\n".join(out) + "\n", changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True)
    ap.add_argument("--in-place", action="store_true")
    a = ap.parse_args()

    src = Path(a.patch).read_text()
    adds = sum(1 for l in src.splitlines()
               if l.startswith("+") and not l.startswith("+++"))
    rems = sum(1 for l in src.splitlines()
               if l.startswith("-") and not l.startswith("---"))
    if adds == 0 and rems == 0:
        sys.exit("this diff changes nothing (no + or - lines) -- not repairable, "
                 "and it must not be run as an arm")

    fixed, changes = fix(src)
    if a.in_place:
        Path(a.patch).write_text(fixed)
        print(f"rewrote {a.patch}")
    else:
        sys.stdout.write(fixed)

    for before, after in changes:
        print(f"  {before}  ->  {after}", file=sys.stderr)
    print(f"  {len(changes)} hunk header(s) corrected; body untouched "
          f"(+{adds} -{rems})", file=sys.stderr)


if __name__ == "__main__":
    main()
