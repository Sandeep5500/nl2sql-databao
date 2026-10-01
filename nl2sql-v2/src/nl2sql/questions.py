"""Loading benchmark questions, with an optional local overlay.

Spider2 is a git submodule pointing at the upstream repo, so editing
`spider2-lite.jsonl` in place is not an option: the edit is not tracked by this
repo (only the submodule SHA is), it is lost on the next submodule update, and it
silently makes our numbers incomparable with everyone else's.

So corrections live in `question_overrides.json` in THIS repo and are applied at
load time, off by default. Each entry records the upstream text it was written
against; if upstream changes that text the override is refused rather than
silently applied to a question it no longer describes.

Two kinds, which must not be confused:

  clarify          The question is ambiguous or underspecified, and the gold
                   answer is consistent with one reading. Saying which reading is
                   meant is a fair test of SQL ability, and a model that gains
                   from it would gain on a real user's clearer question too.

  contradicts-gold The question states something the gold answer does not do
                   (local272 says warehouse 1; three of the gold's four rows are
                   warehouse 2). Rewriting the question to match the gold is
                   teaching to the test: the score rises without the model
                   getting better. The honest action is to EXCLUDE the question
                   and report the smaller denominator, which is what `action`
                   defaults to for this kind.

Scores from an overlay run are not comparable to the leaderboard, so every
consumer records which questions were touched (see `applied`).
"""

import json
from pathlib import Path

from nl2sql.config import QUESTIONS_FILE, REPO_ROOT

OVERRIDES_FILE = REPO_ROOT / "nl2sql-v2" / "question_overrides.json"
KINDS = {"clarify", "contradicts-gold"}
MODES = {"off", "clarify", "all"}


def load_overrides(path: Path = OVERRIDES_FILE) -> dict:
    if not path.exists():
        return {}
    blob = json.loads(path.read_text())
    return blob.get("overrides", blob)


def apply_overrides(questions: list[dict], mode: str = "off",
                    path: Path = OVERRIDES_FILE) -> tuple[list[dict], list[dict]]:
    """Returns (questions, applied). `applied` is the audit trail to store in traces.

    mode "off"     -> untouched upstream questions (the default everywhere)
         "clarify" -> apply only kind="clarify"
         "all"     -> also act on kind="contradicts-gold"
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    if mode == "off":
        return questions, []

    ov = load_overrides(path)
    out, applied = [], []
    for q in questions:
        e = ov.get(q["instance_id"])
        if not e or (mode == "clarify" and e["kind"] != "clarify"):
            out.append(q)
            continue
        # Refuse to apply an override written against different upstream text.
        if e.get("upstream_question") and e["upstream_question"].strip() != q["question"].strip():
            raise SystemExit(
                f"{q['instance_id']}: upstream question text has changed since this "
                f"override was written. Re-verify it against the gold answer and update "
                f"'upstream_question' in {path.name}, or remove the entry.")
        action = e.get("action") or ("exclude" if e["kind"] == "contradicts-gold" else "replace")
        rec = {"instance_id": q["instance_id"], "kind": e["kind"], "action": action,
               "reason": e.get("reason", "")}
        if action == "exclude":
            applied.append(rec)
            continue          # dropped: the denominator shrinks, and that is reported
        q = dict(q, question=e["question"])
        applied.append(rec)
        out.append(q)
    return out, applied


def load_questions(instances=None, skip=None, limit=None, local_only=True,
                   override_mode: str = "off") -> tuple[list[dict], list[dict]]:
    out = []
    with open(QUESTIONS_FILE) as f:
        for line in f:
            q = json.loads(line)
            iid = q["instance_id"]
            if local_only and not iid.startswith("local"):
                continue
            if instances and iid not in instances:
                continue
            if skip and iid in skip:
                continue
            out.append(q)
    out, applied = apply_overrides(out, override_mode)
    return (out[:limit] if limit else out), applied
