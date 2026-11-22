"""Give the proposer its validation errors and the real file, and ask it to fix
its own patch.

Round 1 produced a sound diagnosis with an unapplicable diff: it named
`preview_rows` when the field is `preview_rows_default`, and emitted a bare `@@`
hunk header. That is a mechanical failure, not a bad idea -- so the loop should
repair rather than discard, and the proposer should do the repairing. Hand-editing
the patch would make the human a co-author of the change being measured.

Cheap: only the target files and the error list are sent, not the trace bundle.

Usage:
    OPENAI_API_KEY=... python rsi_repair.py --round-dir rounds/r1
"""
import argparse, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rsi_propose import (BASE_URL, MODEL, extract_patch, validate_patch,
                         key_spend)

SYSTEM = """\
Your previous patch was rejected because it does not apply to the real files.
The reasoning behind it was accepted -- only the diff is wrong.

Produce a corrected unified diff. Requirements:
  - every removed line must match the file EXACTLY as given below
  - hunk headers must carry real line ranges, e.g. `@@ -49,2 +49,6 @@`
  - change nothing beyond what your original patch intended
  - keep the explanatory comment you wrote

Reply with ONLY the diff, in a ```diff fenced block.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round-dir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--repo-root",
                    default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--max-tokens", type=int, default=4000)
    a = ap.parse_args()

    rd = Path(a.round_dir)
    patch = (rd / "arm.patch").read_text()
    val = json.loads((rd / "validation.json").read_text())
    problems = val.get("problems") or []

    # the files the patch targets, with line numbers so ranges can be right
    targets = sorted({m.group(1) for m in
                      re.finditer(r"^\+\+\+\s+[ab]/(\S+)", patch, re.M)})
    shown = []
    for t in targets:
        f = Path(a.repo_root) / t
        if not f.exists():
            shown.append(f"### {t}\n(file does not exist)")
            continue
        numbered = "\n".join(f"{i+1:>4}  {l}"
                             for i, l in enumerate(f.read_text().splitlines()))
        shown.append(f"### {t}  (with line numbers)\n```\n{numbered}\n```")

    user = (f"## Your rejected patch\n```diff\n{patch}\n```\n\n"
            f"## Why it was rejected\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\n## The actual files\n\n" + "\n\n".join(shown))

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is not set.")
    from openai import OpenAI

    s0 = key_spend(a.base_url, key)
    client = OpenAI(base_url=a.base_url, api_key=key)
    resp = client.chat.completions.create(
        model=a.model, max_tokens=a.max_tokens,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": user}])
    text = resp.choices[0].message.content or ""
    (rd / "repair_response.md").write_text(text)

    new = extract_patch(text)
    if not new:
        sys.exit("the repair reply contained no diff")
    ok, probs = validate_patch(new, a.repo_root)
    (rd / "arm.patch.repaired").write_text(new)
    if ok:
        (rd / "arm.patch").write_text(new)

    u = resp.usage
    print(f"in {u.prompt_tokens} tok, out {u.completion_tokens} tok")
    print(f"\n=== repaired patch: {'PASS' if ok else 'STILL REJECTED'} ===")
    for p in probs:
        print(f"   - {p}")
    print()
    print(new)
    val.update({"repaired": ok, "repair_problems": probs})
    (rd / "validation.json").write_text(json.dumps(val, indent=2))


if __name__ == "__main__":
    main()
