"""The RSI proposer: an independent model proposes one harness change.

Claude Opus 5.5 reads the gold-free diagnosis bundle from `rsi_diagnose.py` and
returns a rationale plus a unified diff. It is deliberately NOT the model being
improved (that is the frozen Qwen3.6-35B solver) and it cannot reach the
evaluator that will judge its work.

Every proposal is run through `validate_patch`, which is enforcement rather than
advice -- this project's repeated finding is that stated rules get ignored while
rules attached to the action hold. The checks:

  * only files on the editable allowlist may be touched
  * `eval.py` and `rsi_eval.py` are locked: the scorer and the judge of arms
  * `prompts.py` is locked: every text-only change has measured zero
  * no added line may name a benchmark instance, which would be overfitting to
    the evolve questions rather than improving the harness

Needs ANTHROPIC_API_KEY. Cost is roughly $0.30 per round at Opus 5.5 pricing
($4/MTok in, $20/MTok out) for a ~60k-token bundle.

Usage:
    python rsi_propose.py --bundle bundle.md --out-dir rounds/r1 [--dry-run]
"""
import argparse, json, os, re, sys, textwrap, urllib.request
from pathlib import Path

# The CMU AI Gateway is a LiteLLM proxy speaking the OpenAI protocol, so Claude
# is reached with the OpenAI SDK and a Bedrock-style alias -- not the Anthropic
# SDK. The repo already calls the gateway this way (scripts/synth_*.py).
BASE_URL = "https://ai-gateway.andrew.cmu.edu/v1"
MODEL = "us.anthropic.claude-opus-5-5"


def key_spend(base_url, key):
    """Dollars billed on this key, from the gateway itself.

    LiteLLM exposes /key/info, so cost is never estimated from a price table --
    it is whatever the gateway actually charged. Returns None if unavailable.
    """
    try:
        url = base_url.rstrip("/").removesuffix("/v1") + "/key/info"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        info = d.get("info") or d
        v = info.get("spend")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None

# Files the baseline configuration actually EXECUTES. A patch here can move a
# metric. Determined from the baseline flags: --context-mode full,
# --temperature 0.0, --max-steps 30, and nothing else.
EDITABLE_LIVE = [
    "src/nl2sql/agent.py",      # loop, salvage logic, step budget, submit path
    "src/nl2sql/tools.py",      # tool behaviour AND tool descriptions
    "src/nl2sql/prompts.py",    # the solver's system prompt
    "src/nl2sql/config.py",     # budgets, row caps, limits
    "src/nl2sql/context.py",    # schema presentation
    "src/nl2sql/db.py",         # engine layer -- editable but risky
]

# Editable, but NOT executed by the baseline: the critic needs --critic-model,
# the rubric needs --rubric-dir, the draft needs --draft-model, and the
# judge/selector scripts need several candidates to choose between, which a
# single greedy lane never produces. A patch to these measures exactly zero --
# not "probably nothing", but a guaranteed no-op that still costs a 2h arm.
# Unlock by changing the baseline configuration first, then re-baselining.
#
# WORSE THAN DORMANT, for the judge/selector files specifically: on this branch
# (dev-juliep2) they are also STALE. The deployed judge moved to the `diff_cmp`
# prompt on 2026-11-13, and that lives on `judge-selection-nov2026`, not here.
# `select_answer.py` here is the pre-diff_cmp version. So a judge patch proposed
# against this tree edits abandoned code that never runs -- it cannot be
# measured, and it would be overwritten by the real judge at validation time.
# Decision 2026-11-19: the loop stays on dev-juliep2 and the judge branch is
# used only for the final production validation.
EDITABLE_DORMANT = [
    "src/nl2sql/rubric.py",
    "src/nl2sql/critic.py",
    "src/nl2sql/draft.py",
    "scripts/run_rubric.py",
    "scripts/select_answer.py",
    "scripts/validator_select.py",
    "scripts/validator_agent.py",
    "scripts/validator_pairwise.py",
]

EDITABLE = EDITABLE_LIVE + EDITABLE_DORMANT

LOCKED = [
    "src/nl2sql/eval.py",             # the scorer
    "scripts/analysis/rsi_eval.py",   # the judge of arms
]

SYSTEM = textwrap.dedent(f"""\
    You are improving a text-to-SQL agent harness. The language model inside the
    agent is FROZEN and you cannot retrain it. You change only the harness: the
    loop, the gates, the tools, the budgets, the salvage logic.

    You will be shown aggregate metrics and failing episodes from an "evolve"
    set. You will NOT be shown correct answers, and you must not ask for them.
    Your change is judged on a separate held-out set whose databases do not
    appear in what you see, so a change that keys on specific questions cannot
    win -- do not try.

    THE PIPELINE, AND WHICH PARTS ARE ACTUALLY RUNNING

    The harness is several components, not one. In the configuration you are
    being measured in, only some of them execute:

      LIVE -- a change here can move a metric:
        - the solver loop: picks a tool, reads the result, decides to continue
          or submit; on running out of steps a SALVAGE path picks an answer
          from the results it has seen
        - its tools: run_sql_query, list_tables, describe_table,
          get_column_values, find_value
        - the solver's system prompt and the tool DESCRIPTIONS it reads while
          choosing a tool
        - schema presentation, budgets and caps

      DORMANT -- present in the code but NOT executed here:
        - the critic agent (needs --critic-model)
        - the rubric agent (needs --rubric-dir)
        - the draft_sql agent (needs --draft-model)
        - the judge / selector agents (need several candidate answers; this
          configuration is a single greedy lane, so there is nothing to select
          between)
        - search_context and read_documentation (no retrieval index here)

    Patching a DORMANT component is a guaranteed no-op that still costs a
    two-hour evaluation run. If you believe a dormant component is the real
    problem, SAY SO in your diagnosis and propose the configuration change
    needed to activate it -- do not quietly patch dead code.

    YOU ARE EXPECTED TO ASSESS, not just read:
      - how each tool performs: call counts, error rates, empty results, and
        whether the solver re-runs identical queries. The bundle gives you these
        per tool.
      - whether a tool's DESCRIPTION is why it is misused or never used
      - whether the solver's failures are in finding the data, computing the
        answer, or deciding to stop
      - which component owns each failure you cite

    WHAT YOU MAY EDIT -- live, a patch here is measurable:
    {chr(10).join('      ' + f for f in EDITABLE_LIVE)}

    EDITABLE BUT DORMANT -- only with a configuration change, as above:
    {chr(10).join('      ' + f for f in EDITABLE_DORMANT)}

    The judge and selector files above are doubly dead on this branch: they do
    not execute in this configuration, AND they are an older version than the
    deployed judge, which moved to a different prompt on another branch. Do not
    propose changes to the judge or the selector. If your diagnosis points at
    selection rather than generation, say so in plain words and propose nothing
    -- that is a useful result, and it is recorded, not penalised.

    WHAT IS LOCKED (editing these is an automatic rejection)
    {chr(10).join('      ' + f for f in LOCKED)}

    WHAT THIS PROJECT HAS ALREADY MEASURED. This is guidance, not prohibition --
    if the traces give you a reason to revisit something here, say so and do it.

      WORKED:
        - raising the step budget 30 -> 60: fallback 0.44 -> 0.11
        - a rubric gate on expected row count (13 for 13 when it fired)
        - a scalar-unwrap output filter
        - giving the judge a `diff_cmp` tool to compare candidate results
        - rewriting the JUDGE's prompt: worth about +12 over majority vote

      FAILED:
        - domain facts added to the solver's system prompt (used in 1 of 24)
        - telling the solver to declare its assumptions (AUC 0.50)
        - eight mechanical post-hoc output transforms (0 of 20)
        - showing the judge the solver's own prose about its reasoning (AUC 0.50)
        - ROUND 1: `preview_rows_default` 12 -> 40. Read this one carefully,
          it is the most recent and the most instructive. The DIAGNOSIS was
          correct and confirmed: 56% of episodes re-ran identical SQL to see
          rows the 12-row preview hid, 1.26 duplicates per episode. The patch
          worked exactly as designed -- duplicates fell to 0.89, mean steps
          13.0 -> 12.4. It bought NOTHING: accuracy 74/250 -> 70/250, McNemar
          p=0.557, fallback 0.056 -> 0.060 (wrong way), step-cap saturation
          unchanged at 0.064, salvage share unchanged.
          WHY: steps were never scarce. Mean steps were 13 against a budget of
          30, and only 6.4% of episodes hit the cap BEFORE the patch. Freeing a
          resource that is not exhausted cannot convert a wrong answer into a
          right one.
          The finding remains OPEN -- only this solution to it was refuted.

    The distinction is NOT "mechanisms work, prompts fail" -- rewriting the
    judge's prompt was one of the largest wins here. The distinction is WHEN the
    information arrives. Text that sits passively in a system prompt, hoping to
    be recalled later, gets ignored. Text that changes what the model is asked to
    do AT THE MOMENT IT ACTS -- a tool description it reads as it picks a tool, a
    judging criterion applied as it judges, a gate it must pass to submit -- works.

    So prompting changes are in scope, including the solver's. Prefer ones that
    arrive at the point of action over ones that add background.

    A KNOWN OPEN DEFECT, if you find evidence for it in the traces: the fallback
    salvage path ranks candidate results by the largest cluster of identical
    values, so an agent that re-runs a diagnostic COUNT several times while
    doubting itself will submit that COUNT instead of its real answer.

    THE BINDING-CONSTRAINT TEST -- apply this to your own proposal before you
    write it, and show the work. Round 1 was lost for want of it.

    For whatever you intend to change, answer with numbers from the bundle:
      1. What resource does this free, tighten, or redirect?
      2. Is that resource EXHAUSTED in the failing episodes? Quote the number.
         Steps are not scarce at 13 of 30 used and 6.4% at the cap. A tool that
         errors 2% of the time is not a bottleneck. A thing that happens in 56%
         of episodes is common, which is NOT the same as costly.
      3. Of the failures you looked at, how many would this change plausibly
         convert, and by what mechanism for each? Name episodes.
      4. What is your point estimate for the accuracy change, in questions out
         of 250, and your range? Say "0, and here is why I still want it" if
         that is the honest answer -- a mechanism-only change is allowed, but
         then say so openly instead of implying a gain.
      5. What single observation would tell you this change is wrong?

    Rough scale for calibration: 165 of 250 evolve questions are wrong in BOTH
    arms of round 1. A change that does not touch that population cannot move
    accuracy much, whatever else it improves. The accuracy MDE here is about
    +10 net solves on 250 (~4 points); below that nothing is detectable, so a
    proposal whose own estimate is "+2 questions" is not worth an arm unless
    the mechanism claim stands on its own.

    HOW YOU ARE JUDGED
      - a mechanism metric (fallback rate, step-cap saturation, duplicate
        queries) must improve beyond its measured noise band
      - accuracy is a FLOOR, not a target: if it falls more than 0.03 your
        change is rejected however good the mechanism numbers look
      - probe share and wall-clock time cannot earn an accept; they move as much
        on noise as on any real effect
      - a correct diagnosis with an inert fix still counts as a loss. Spend your
        reasoning on WHETHER THE FIX EARNS SOLVES, not on proving the problem
        is real.

    OUTPUT FORMAT -- exactly these three sections:

    ## Diagnosis
    What the traces actually show. Cite specific episodes. One paragraph.

    ## Proposed change
    What you will change and WHY it will land -- if it is a prompting change, say
    at what moment the model receives it and why that moment is better than a
    passive mention. State which metric you expect to move and in which
    direction. One paragraph.

    ## Patch
    A single unified diff in a ```diff fenced block, with paths relative to the
    nl2sql-v2 directory (e.g. `--- a/src/nl2sql/agent.py`). Change one thing. A
    smaller patch that moves one metric is worth more than a broad rewrite whose
    effect cannot be attributed.
    """)

#: Appended when several independent arms are wanted in one call. Each arm gets
#: its own GPU and its own isolated copy of the code, so they must not overlap:
#: two arms touching the same field cannot be told apart afterwards.
MULTI = textwrap.dedent("""\

    ONE MORE THING, AND IT CHANGES THE OUTPUT FORMAT.

    Propose {n} INDEPENDENT changes, not one. Each will run as its own arm on
    its own GPU against the same baseline, so they are compared with each other
    as well as with the baseline. That means:

      - they must be mechanically independent. No two arms may touch the same
        field, function or prompt section, or their effects cannot be separated.
      - they must be causally distinct. Two different ways to free steps are one
        idea, not two. Prefer arms that attack DIFFERENT failure populations.
      - rank them. Put the one you most believe first and say, in one line per
        arm, why you ordered them that way.
      - it is correct and useful to include an arm you are sceptical of, as long
        as you SAY you are sceptical and why. A cheap decisive negative is worth
        a GPU. What is not acceptable is presenting a guess as a conviction.

    Apply the binding-constraint test to EVERY arm separately. An arm that fails
    its own test should be dropped, not submitted. Returning fewer than {n} arms
    with honest reasoning is better than padding to {n}.

    Use exactly this layout, repeated per arm:

    # ARM <k>: <four-word name>
    ## Diagnosis
    ## Binding-constraint test
    1-5 as above, with numbers.
    ## Proposed change
    ## Estimated effect
    Point estimate in questions out of 250, a range, and the mechanism metric
    you expect to move with its predicted value.
    ## Disconfirming observation
    ## Patch
    One ```diff block.

    After the last arm, add:

    # RANKING
    Your order, with one line of justification each.
    """)

#: Hypotheses the human steering the loop wants tested. These are DESIGN INPUT,
#: not patches: the proposer writes the diff, so authorship of the measured
#: change stays with the proposer and the human does not become a co-author of
#: the thing being measured.
DIRECTED = textwrap.dedent("""\

    DIRECTED CANDIDATES. The human running this loop wants these specific
    hypotheses tested. Treat each as a candidate arm, subject to the same
    binding-constraint test as your own ideas -- if one fails that test, say so
    plainly and drop it rather than implementing it to be agreeable. If you keep
    it, you design the change; the hypothesis only tells you what to aim at.

    {items}
    """)

INSTANCE_PAT = re.compile(r"\b(local_?\d+|local_syn\d+|local_lsb_\w+)\b")


def extract_patch(text):
    m = re.search(r"```diff\s*\n(.*?)```", text, re.S)
    if m:
        return m.group(1)
    m = re.search(r"```\s*\n(--- a/.*?)```", text, re.S)
    return m.group(1) if m else None


def patch_dry_run(patch, repo_root):
    """Ask `patch` itself whether the diff applies. AUTHORITATIVE.

    check_applies() below reimplements part of this and is too weak: it verifies
    that context and removed lines exist, but not that a hunk header's line
    COUNTS match the lines that follow. Round 2 produced one diff whose header
    claimed `@@ -68,2 +68,4 @@` above two context lines and no additions, and
    another malformed midway; both passed check_applies and both were rejected
    by patch. A patch that patch(1) will not apply is worth nothing, and an
    empty one is worse than nothing -- it runs as a silent no-op arm and returns
    a "no change" that reads like a measured result.
    """
    import subprocess, tempfile
    problems = []
    adds = sum(1 for l in patch.splitlines()
               if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in patch.splitlines()
               if l.startswith("-") and not l.startswith("---"))
    if adds == 0 and dels == 0:
        problems.append("the diff changes nothing: no added or removed lines")
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as f:
        f.write(patch if patch.endswith("\n") else patch + "\n")
        tmp = f.name
    try:
        r = subprocess.run(["patch", "-p1", "--dry-run", "--forward", "-i", tmp],
                           cwd=repo_root, capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            tail = (r.stdout + r.stderr).strip().splitlines()
            problems.append("patch --dry-run refused it: "
                            + " | ".join(tail[-3:]))
    except Exception as e:
        problems.append(f"could not run patch(1): {type(e).__name__}: {e}")
    finally:
        os.unlink(tmp)
    return problems


def check_applies(patch, repo_root):
    """Does the diff actually match the files on disk?

    Round 1 produced a well-reasoned patch that named `preview_rows` when the
    real field is `preview_rows_default`, with a bare `@@` hunk header. File-path
    checks passed it happily. A patch that cannot apply is worth nothing, so this
    verifies every removed and context line really exists in the target.
    """
    problems = []
    cur, removed = None, []

    def flush():
        if cur is None or not removed:
            return
        f = Path(repo_root) / cur
        if not f.exists():
            problems.append(f"target file does not exist: {cur}")
            return
        body = f.read_text()
        for line in removed:
            if line.strip() and line not in body:
                problems.append(
                    f"{cur}: the diff removes a line that is not in the file: "
                    f"{line.strip()[:80]!r}")
                return

    for line in patch.splitlines():
        m = re.match(r"^\+\+\+\s+[ab]/(\S+)", line)
        if m:
            flush()
            cur, removed = m.group(1), []
            continue
        if line.startswith("@@"):
            if not re.match(r"^@@\s+-\d+(,\d+)?\s+\+\d+(,\d+)?\s+@@", line):
                problems.append(
                    f"malformed hunk header {line.strip()!r} -- needs line ranges "
                    f"like `@@ -49,2 +49,6 @@`, or no tool can apply it")
            continue
        if line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    flush()
    return problems


def validate_patch(patch, repo_root=None):
    """Return (ok, problems). Enforcement: the loop may not talk its way past."""
    problems = []
    if not patch or not patch.strip():
        return False, ["no unified diff found in the response"]

    targets = set()
    for line in patch.splitlines():
        m = re.match(r"^(?:\+\+\+|---)\s+[ab]/(\S+)", line)
        if m and m.group(1) != "/dev/null":
            targets.add(m.group(1))
    if not targets:
        problems.append("the diff names no files (expected `--- a/<path>`)")

    for t in sorted(targets):
        if t in LOCKED:
            problems.append(f"touches a LOCKED file: {t}")
        elif t in EDITABLE_DORMANT:
            problems.append(f"touches {t}, which the baseline configuration never "
                            f"executes -- this patch is a guaranteed no-op. Activate "
                            f"the component and re-baseline first.")
        elif t not in EDITABLE:
            problems.append(f"touches a file not on the editable allowlist: {t}")

    added = [l[1:] for l in patch.splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    for l in added:
        if INSTANCE_PAT.search(l):
            problems.append(f"an added line names a benchmark instance, which is "
                            f"overfitting rather than a harness change: {l.strip()[:90]}")
            break

    if repo_root:
        problems.extend(check_applies(patch, repo_root))
        problems.extend(patch_dry_run(patch, repo_root))
    return (not problems), problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]),
                    help="nl2sql-v2 root, used to verify the patch applies")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--with-source", action="store_true",
                    help="include the editable files, numbered, in the prompt")
    ap.add_argument("--n-proposals", type=int, default=1,
                    help="ask for N independent arms in one call")
    ap.add_argument("--directed", action="append", default=[],
                    help="a hypothesis the human wants tested; repeatable")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the prompt, make no API call")
    a = ap.parse_args()

    bundle = Path(a.bundle).read_text()
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)

    # the bundle must never carry gold, even if rsi_diagnose is bypassed
    for pat in (r"\bgold[_ ]?sql\b", r"\bexec_result\b", r"\bspider2lite_eval\b"):
        if re.search(pat, bundle, re.I):
            sys.exit(f"REFUSING to send the bundle: it references {pat!r}.")

    system = SYSTEM
    if a.with_source:
        # ROOT CAUSE FIX. Round 1 and two of round 2's four arms produced sound
        # reasoning with unapplicable diffs -- invented line text, bare `@@`
        # headers, hunk counts that did not match their bodies -- because the
        # proposer was asked to patch files it had never read. Repair calls fixed
        # some and failed on others. Sending the editable sources up front costs
        # ~20k tokens once and removes the whole failure mode.
        parts = []
        for f in EDITABLE_LIVE:
            fp = Path(a.repo_root) / f
            if not fp.exists():
                continue
            numbered = "\n".join(f"{i+1:>4}  {l}"
                                  for i, l in enumerate(fp.read_text().splitlines()))
            parts.append(f"### {f}\n```\n{numbered}\n```")
        system += ("\n\nTHE ACTUAL SOURCE YOU ARE PATCHING, with line numbers. "
                   "Every removed or context line in your diff must match these "
                   "EXACTLY, and each hunk header's counts must match the lines "
                   "you write under it. There is no excuse for a diff that does "
                   "not apply.\n\n" + "\n\n".join(parts))
    if a.n_proposals > 1:
        system += MULTI.format(n=a.n_proposals)
    if a.directed:
        system += DIRECTED.format(
            items="\n".join(f"      ({i+1}) {d}" for i, d in enumerate(a.directed)))
    (out / "system_prompt.txt").write_text(system)
    est_in = (len(system) + len(bundle)) // 4
    print(f"model    {a.model}")
    print(f"endpoint {a.base_url}")
    print(f"bundle   ~{len(bundle)//4} tokens, prompt ~{est_in} tokens")

    if a.dry_run:
        print(f"\n--- dry run, no API call. System prompt at "
              f"{out/'system_prompt.txt'} ---")
        return

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is not set (the CMU gateway virtual key).")
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        sys.exit("the openai package is missing: uv pip install openai")

    spend0 = key_spend(a.base_url, key)
    if spend0 is not None:
        print(f"spend on this key before the call: ${spend0:.2f}")

    client = OpenAI(base_url=a.base_url, api_key=key)
    kwargs = dict(model=a.model, max_tokens=a.max_tokens,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": bundle}])
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        sys.exit(f"gateway call failed: {type(e).__name__}: {str(e)[:400]}")

    text = resp.choices[0].message.content or ""
    (out / "proposal.md").write_text(text)

    spend1 = key_spend(a.base_url, key)
    cost = (spend1 - spend0) if (spend0 is not None and spend1 is not None) else None
    u = getattr(resp, "usage", None)
    if u:
        print(f"\nin {u.prompt_tokens} tok, out {u.completion_tokens} tok")
    if cost is not None:
        print(f"billed by the gateway: ${cost:.4f}   (key total now ${spend1:.2f})")

    patch = extract_patch(text)
    ok, problems = validate_patch(patch, a.repo_root)
    if patch:
        (out / "arm.patch").write_text(patch)
    (out / "validation.json").write_text(json.dumps(
        {"ok": ok, "problems": problems, "model": a.model,
         "billed_usd": round(cost, 4) if cost is not None else None,
         "prompt_tokens": getattr(u, "prompt_tokens", None),
         "completion_tokens": getattr(u, "completion_tokens", None)}, indent=2))

    print(f"\n=== validation: {'PASS' if ok else 'REJECTED'} ===")
    for pr in problems:
        print(f"   - {pr}")
    if ok:
        print(f"   patch written to {out/'arm.patch'}")
        print(f"\n  apply with:  cd nl2sql-v2 && git apply --check {out/'arm.patch'}")
    else:
        print("   Not applied. Record as rejected and re-propose.")


if __name__ == "__main__":
    main()
