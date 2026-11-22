#!/usr/bin/env python3
"""Tool-using judge: let the validator query the database before it picks.

Why this and not a better static judge. The measured error breakdown says the
information a static judge needs is not in its input:

  * wrong_values is the largest error class, and a results-only judge scores at
    chance on it -- you cannot see that 1,284 should have been 1,312;
  * set_vs_grain never moved under fine-tuning, in any arm at any data size;
  * 67% of mixed questions have a wrong result group whose (rows, cols) exactly
    matches a correct group's, so shape heuristics cannot separate them.

Tools do not make the model a better pattern matcher. They let it recompute the
disputed number, count distinct keys to settle the grain, and look at how a
filter column actually stores its values. That is new information.

It picks among the given candidates and has no submit path of its own, so it
cannot quietly turn into a re-generation of the answer -- which would be a worse
judge, since pass@1 is below the current judge's score.

Reads validator_inputs.json, the same byte-identical input the static judge
uses, so the comparison is fair. Nothing derived from the gold SQL or the gold
output is ever put in a prompt; `correct` travels alongside for scoring only.

Usage (from nl2sql-v2/):
    uv run python scripts/validator_agent.py \
        --inputs validator_inputs_rg.json \
        --db-dir ../Spider2/spider2-lite/resource/databases/spider2-localdb \
        --endpoint http://node:8765/v1 --model Qwen/Qwen3.5-9B \
        --out ../results/validator_agent.csv --workers 4
"""

import argparse
import collections
import csv
import io
import json
import os
import random
import re
import zlib
import sys
import threading
import time
from pathlib import Path

# NL2SQL_SRC lets this run from anywhere (e.g. $HOME on a cluster node, where
# the repo-relative guess resolves to "/src").
_src = os.environ.get("NL2SQL_SRC") or str(Path(__file__).resolve().parents[1] / "src")
if not (Path(_src) / "nl2sql").is_dir():
    sys.exit(f"cannot find the nl2sql package at {_src!r}; set NL2SQL_SRC to "
             "<repo>/nl2sql-v2/src")
sys.path.insert(0, _src)

from openai import OpenAI                                     # noqa: E402
from nl2sql.config import AgentConfig                         # noqa: E402
from nl2sql.db import Database                                # noqa: E402
from nl2sql.tools import ToolSession, build_tool_schemas, parse_tool_args  # noqa: E402

SYSTEM = """You are the judge. {n} candidate answers to one question were produced \
independently by a SQL agent. Exactly one choice is yours to make: which candidate \
correctly answers the question.

You have read-only access to the same database the candidates ran against. Use it. \
Do not take a candidate's word for its result -- check the parts that decide the \
answer:

- Recompute the number. If candidates disagree on a total, an average or a count, \
write your own query for it and see which one matches.
- Settle the grain. If the question asks for one row and a candidate returns many \
(or the reverse), count the distinct keys yourself and see which grain the question \
actually implies.
- Check the joins. A join on a non-unique key multiplies rows and inflates every \
SUM downstream. Count rows before and after a suspect join.
- Check the filters. Look at how the column really stores its values before \
believing a WHERE clause matches what the question asked for.

The question:
{question}
{doc_hint}
Database: {db_name}
{extra}
The candidates:
{candidates}

You have {max_steps} steps. When you are ready, call choose_candidate exactly once. \
You must choose one of the labels above -- you cannot submit an answer of your own, \
and you cannot decline. If your checks leave two candidates equally defensible, pick \
the one whose SQL most directly expresses what the question asked for."""

# --- variant blocks, each testing one measured failure ------------------------

# The judge spent 237 of ~770 tool calls on list_tables/describe_table, i.e. a
# third of its budget rediscovering the schema. Hand it over instead.
SCHEMA_NOTE = """
Schema of the tables these candidates use:
{schema}
"""

# Measured: the judge rejected a candidate for returning extra columns, which
# the scorer tolerates. Align its criterion with how the answer is actually
# graded, so it stops failing candidates on cosmetics.
SCORER_NOTE = """
How the answer is graded, so you judge the right thing:
- Every column the question asks for must be present, with the right values.
- EXTRA columns are tolerated. Do not reject a candidate for returning more
  columns than asked, or for column names or column order.
- Row order matters only when the question asks for an ordering.
- A numeric value must match; rounding to the asked-for precision is fine.
Judge the values, not the presentation.
"""

# Measured: three of nine remaining 1-of-4 failures turn on one discriminating
# fact the judge never looked at -- a column count, a string-wrapped number, a
# row set that collapses under normalisation. Enforcing those as hard filters
# LOSES ground (A1b -1, A3 -3 on the 49 mixed: they identify the bad candidate
# without identifying the good one). So state the facts and let the judge weigh
# them, instead of overriding it with a rule that is right 43% of the time.
DIFF_NOTE = """
Computed differences between the candidates. These are facts about their
results, not opinions about which is right -- you still have to decide:
{facts}
Work out which of these differences the question actually settles. A difference
that the question does not speak to is not a reason to reject a candidate.
"""


def diff_facts(shown):
    """Discriminating facts between candidate results, computed not guessed."""
    out = []

    def shape(c):
        sh = c.get("shape")
        return tuple(sh) if isinstance(sh, (list, tuple)) and len(sh) == 2 else (0, 0)

    def parsed(c):
        pv = (c.get("preview") or "").strip()
        if not pv:
            return [], []
        try:
            rd = list(csv.reader(io.StringIO(pv)))
        except Exception:
            return [], []
        return (rd[0] if rd else []), rd[1:]

    # which candidates returned the same thing, and which stand alone
    groups = collections.defaultdict(list)
    for c in shown:
        h, rs = parsed(c)
        groups[(shape(c), tuple(tuple(r) for r in rs))].append(c["label"])
    same = [g for g in groups.values() if len(g) > 1]
    if same:
        out.append("- identical results: " +
                   "; ".join("[" + "] and [".join(g) + "] agree" for g in same) +
                   ". Agreement is not correctness: several candidates can repeat "
                   "the same misreading.")

    # same row count, different column count -- the scorer tolerates extra
    # columns but a MISSING required column fails
    by_rows = collections.defaultdict(list)
    for c in shown:
        by_rows[shape(c)[0]].append(c)
    for nr, grp in sorted(by_rows.items()):
        widths = {shape(c)[1] for c in grp}
        if len(grp) > 1 and len(widths) > 1:
            desc = ", ".join(f"[{c['label']}] {shape(c)[1]} cols "
                             f"({', '.join(parsed(c)[0]) or '?'})" for c in grp)
            out.append(f"- all return {nr} rows but differ in width: {desc}. "
                       "A column the question asks for that is MISSING is fatal; "
                       "a column that is extra is ignored.")

    # a column of 'Tier 1','Tier 2' where another candidate has 1,2
    wrap = re.compile(r"^\s*[A-Za-z][A-Za-z ._-]*\s*(\d+(?:\.\d+)?)\s*$")
    bare = {}
    for c in shown:
        _, rs = parsed(c)
        for j, col in enumerate(zip(*rs) if rs else []):
            if col and all(re.fullmatch(r"-?\d+(\.\d+)?", (v or "").strip()) for v in col):
                bare[tuple(str(float(v)) for v in col)] = c["label"]
    for c in shown:
        _, rs = parsed(c)
        for j, col in enumerate(zip(*rs) if rs else []):
            ms = [wrap.fullmatch((v or "").strip()) for v in col]
            if col and all(ms):
                k = tuple(str(float(m.group(1))) for m in ms)
                if k in bare and bare[k] != c["label"]:
                    out.append(f"- [{c['label']}] writes column {j + 1} as text "
                               f"around a number (e.g. {col[0]!r}) where "
                               f"[{bare[k]}] gives the bare value. Decide which "
                               "form the question asks for.")

    # rows that collapse under trivial normalisation of the first column
    for c in shown:
        _, rs = parsed(c)
        if not rs:
            continue
        keys = [(r[0] or "").strip().lower() for r in rs if r]
        norm = [k[:-1] if len(k) > 1 and k.endswith("/") else k for k in keys]
        if len(norm) != len(set(norm)):
            dup = [k for k, n in collections.Counter(norm).items() if n > 1][:3]
            out.append(f"- [{c['label']}] has rows that differ only by a trailing "
                       f"slash or case (e.g. {dup}). If the question means those "
                       "to be one page/key, this candidate double-counts; if it "
                       "means them to be distinct, the others under-count.")

    # row counts, so the grain question is explicit
    shapes = ", ".join(f"[{c['label']}] {shape(c)[0]}x{shape(c)[1]}" for c in shown)
    out.append(f"- shapes: {shapes}.")
    return "\n".join(out)


# Measured: the judge's own verification query often repeats a candidate's
# mistake, and it then confirms that candidate ("matching my verification
# query"). Computing its own answer BEFORE it sees any candidate SQL is the
# direct test of whether anchoring causes that.
OWN_FIRST_SYSTEM = """Answer this question yourself using the database. Work with the tools: look at the schema, write SQL, run it, check it. Do not rush.

The question:
{question}
{doc_hint}
Database: {db_name}

You have {steps} steps. Your last successful run_sql_query is taken as your answer, so make sure the query you are happiest with is the one you run last."""

OWN_ANSWER_NOTE = """
Before seeing these candidates you answered the question yourself:

your SQL:
{sql}
your result ({rows} rows x {cols} columns):
{preview}

Treat this as one more piece of evidence, not as the truth -- you may have made a
mistake too. Where a candidate disagrees with it, find out which of the two is
wrong before you decide.
"""


def tables_in_sql(sqls, known):
    """Table names from the candidates' SQL, matched against the real schema."""
    words = set()
    for q in sqls:
        words |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", q or ""))
    lower = {w.lower() for w in words}
    return [t for t in known if t.lower() in lower]


USER_START = "Begin. Verify what matters, then call choose_candidate."

CAND = """[{label}]
SQL:
{sql}
RESULT ({rows} rows x {cols} columns):
{preview}
"""

# Read-only tools only. submit_result and draft_sql are deliberately absent:
# the judge chooses among candidates, it does not author an answer.
KEEP = {"run_sql_query", "list_tables", "describe_table", "get_column_values",
        "find_value", "search_context", "read_documentation"}

CHOOSE = {"type": "function", "function": {
    "name": "choose_candidate",
    "description": "Name the candidate that correctly answers the question. "
                   "Call this exactly once, as your final action.",
    "parameters": {"type": "object", "properties": {
        "label": {"type": "string", "description": "The label of the chosen candidate."},
        "why": {"type": "string",
                "description": "One sentence: the check that decided it."}},
        "required": ["label", "why"]}}}

_print_lock = threading.Lock()


def render_candidates(cands, preview_rows):
    out = []
    for c in cands:
        rows, cols = (c.get("shape") or ["?", "?"])[:2]
        prev = "\n".join((c.get("preview") or "").splitlines()[: preview_rows + 1])
        out.append(CAND.format(label=c["label"], sql=c["sql"], rows=rows,
                               cols=cols, preview=prev))
    return "\n".join(out)


# Qwen sometimes writes its tool call as markup inside the reasoning channel,
# where the server's reasoning parser swallows it before the tool-call parser
# sees it. The turn then arrives with no tool_calls and, uncorrected, burns a
# step: in a 12-step trace roughly every other turn was lost this way. The main
# generation agent hides the same waste behind a 30-step budget.
_FN = re.compile(r"<function=([A-Za-z_]\w*)>(.*?)</function>", re.DOTALL)
_PARAM = re.compile(r"<parameter=([A-Za-z_]\w*)>(.*?)</parameter>", re.DOTALL)


class _Fn:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class _Call:
    type = "function"

    def __init__(self, i, name, args):
        self.id = f"salvaged_{i}"
        self.function = _Fn(name, args)


def salvage_tool_calls(msg):
    """Recover tool calls the server left as text in content or reasoning."""
    d = msg.model_dump() if hasattr(msg, "model_dump") else {}
    for key in ("content", "reasoning", "reasoning_content"):
        text = d.get(key)
        if not isinstance(text, str) or "<function=" not in text:
            continue
        out = []
        for m in _FN.finditer(text):
            args = {k: v.strip() for k, v in _PARAM.findall(m.group(2))}
            out.append(_Call(len(out), m.group(1), json.dumps(args)))
        if out:
            return out
    return []


def own_answer(client, db, session, cfg, args, rec, db_path, doc_hint):
    """Phase one: answer the question with no candidate in sight.

    Returns the last result the model successfully produced, which phase two
    sees as independent evidence.
    """
    out = {"sql": "", "preview": "", "shape": (0, 0), "steps": 0}
    budget = max(4, args.max_steps // 2)
    tools = [t for t in build_tool_schemas(cfg, has_docs=bool(rec.get("doc")),
                                           has_search=False)
             if t["function"]["name"] in KEEP]
    msgs = [{"role": "system", "content": OWN_FIRST_SYSTEM.format(
                question=rec["question"], doc_hint=doc_hint,
                db_name=db_path.stem, steps=budget)},
            {"role": "user", "content": "Begin."}]
    empty = 0
    for _ in range(budget * 3):
        if out["steps"] >= budget:
            break
        try:
            r = client.chat.completions.create(
                model=args.model, messages=msgs, tools=tools,
                temperature=args.temperature, max_tokens=args.max_tokens)
        except Exception:
            break
        m = r.choices[0].message
        calls = list(m.tool_calls or []) or salvage_tool_calls(m)
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [{"id": c.id, "type": "function",
                                     "function": {"name": c.function.name,
                                                  "arguments": c.function.arguments}}
                                    for c in calls]})
        if not calls:
            empty += 1
            if empty > 3:
                break
            msgs.append({"role": "user", "content": "Call a tool."})
            continue
        out["steps"] += 1
        for c in calls:
            a = parse_tool_args(c.function.arguments)
            res = session.dispatch(c.function.name, a)
            if len(res) > cfg.max_tool_result_chars:
                res = res[: cfg.max_tool_result_chars] + "\n...[truncated]"
            msgs.append({"role": "tool", "tool_call_id": c.id, "content": res})
    # the last query that actually ran is this phase's answer
    if session.query_results:
        qid = max(session.query_results, key=lambda q: int(q[1:]))
        sql, df = session.query_results[qid]
        out["sql"] = sql
        out["shape"] = (len(df), len(df.columns))
        out["preview"] = df.head(args.preview_rows).to_csv(index=False)[:2000]
    return out


def judge_one(iid, rec, args, cfg):
    cands = rec["candidates"]
    labels = [c["label"] for c in cands]
    db_path = Path(args.db_dir) / f"{rec['db']}.sqlite"
    row = {"instance_id": iid, "picked": "", "picked_correct": False, "parsed": False,
           "n_candidates": len(cands),
           "n_correct_available": sum(1 for c in cands if c["correct"]),
           "steps": 0, "salvaged": 0, "own_steps": 0, "own_ok": False,
           "tables_given": 0, "why": "", "status": "no_choice"}
    if not db_path.exists():
        row["status"] = "no_db"
        return row

    db = Database(db_path)
    trace = []
    try:
        session = ToolSession(db=db, cfg=cfg, doc_text=rec.get("doc"))
        tools = [t for t in build_tool_schemas(cfg, has_docs=bool(rec.get("doc")),
                                               has_search=False)
                 if t["function"]["name"] in KEEP] + [CHOOSE]
        doc_hint = ("\nA documentation file ships with this question; "
                    "read_documentation shows it.\n" if rec.get("doc") else "")
        client = OpenAI(base_url=args.endpoint, api_key="x", timeout=args.timeout)

        # Presentation order, not identity. The letters stay with their candidate
        # so scoring is unchanged; shuffling only breaks the alignment between
        # "first in the prompt" and "lane 1", which is where the A-preference
        # (34.5% picked vs 25.7% available) comes from.
        shown = list(cands)
        if args.shuffle_labels:
            random.Random(zlib.crc32(iid.encode())).shuffle(shown)

        extra = ""
        if args.schema_upfront:
            known = db.list_tables()
            tabs = tables_in_sql([c["sql"] for c in cands], known)[:args.max_tables]
            if tabs:
                blocks = []
                for t in tabs:
                    try:
                        blocks.append(db.describe_table(t, context=None))
                    except Exception:
                        pass
                if blocks:
                    extra += SCHEMA_NOTE.format(schema="\n".join(blocks))
                    row["tables_given"] = len(blocks)
        if args.scorer_note:
            extra += SCORER_NOTE
        if args.diff_facts:
            f = diff_facts(shown)
            if f:
                extra += DIFF_NOTE.format(facts=f)

        if args.independent_first:
            own = own_answer(client, db, session, cfg, args, rec, db_path, doc_hint)
            row["own_steps"] = own["steps"]
            if own["sql"]:
                rows_, cols_ = own["shape"]
                extra += OWN_ANSWER_NOTE.format(
                    sql=own["sql"], rows=rows_, cols=cols_, preview=own["preview"])
                row["own_ok"] = True

        system = SYSTEM.format(
            n=len(cands), question=rec["question"], doc_hint=doc_hint,
            db_name=db_path.stem, extra=extra,
            candidates=render_candidates(shown, args.preview_rows),
            max_steps=args.max_steps)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": USER_START}]

        done = False
        empty = 0
        forced = False
        bad_tries = 0
        # A turn that produced no tool call is not charged a step, so the budget
        # buys verification work rather than parser accidents. The hard bound on
        # turns stops a model that will not act from looping forever.
        for _turn in range(args.max_steps * 3):
            kw = dict(model=args.model, messages=messages, tools=tools,
                      temperature=args.temperature, max_tokens=args.max_tokens)
            if row["steps"] >= args.max_steps and not forced:
                # out of budget: make it commit rather than record no_choice
                forced = True
                messages.append({"role": "user", "content":
                                 "Your step budget is spent. Call choose_candidate "
                                 "now with the best-supported candidate."})
                kw["messages"] = messages
                kw["tool_choice"] = {"type": "function",
                                     "function": {"name": "choose_candidate"}}
            elif forced:
                kw["tool_choice"] = {"type": "function",
                                     "function": {"name": "choose_candidate"}}
            try:
                r = client.chat.completions.create(**kw)
            except Exception:
                if "tool_choice" not in kw:
                    raise
                kw.pop("tool_choice")          # server may refuse a named choice
                r = client.chat.completions.create(**kw)
            m = r.choices[0].message
            calls = list(m.tool_calls or [])
            if not calls:
                calls = salvage_tool_calls(m)
                if calls:
                    row["salvaged"] += 1
            messages.append({"role": "assistant", "content": m.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name,
                                                          "arguments": c.function.arguments}}
                                            for c in calls]})
            if not calls:
                empty += 1
                if empty > 3 and not forced:
                    # It is not going to act. Make it commit: abandoning the
                    # question scores zero even where every candidate is correct,
                    # which a static judge never does.
                    forced = True
                    messages.append({"role": "user", "content":
                                     "Stop exploring and decide now. Call "
                                     "choose_candidate with the candidate your "
                                     "checks best support."})
                    continue
                if empty > 7:
                    row["status"] = "no_action"
                    break
                messages.append({"role": "user", "content":
                                 "Call a tool, or call choose_candidate."})
                continue
            row["steps"] += 1
            for c in calls:
                name = c.function.name
                a = parse_tool_args(c.function.arguments)
                if name == "choose_candidate":
                    pick = str(a.get("label", "")).strip().strip("[]").upper()
                    row["why"] = str(a.get("why", ""))[:500]
                    if pick in labels:
                        row["picked"] = pick
                        row["parsed"] = True
                        row["status"] = "chose"
                        row["picked_correct"] = next(
                            x["correct"] for x in cands if x["label"] == pick)
                    elif bad_tries < 2:
                        # a malformed label is a formatting slip, not a decision
                        bad_tries += 1
                        row["status"] = "bad_label"
                        messages.append({"role": "tool", "tool_call_id": c.id,
                                         "content": f"ERROR: {pick!r} is not a "
                                         f"candidate label. Choose exactly one of: "
                                         f"{', '.join(labels)}."})
                        break
                    else:
                        row["status"] = "bad_label"
                    if row["parsed"] or bad_tries >= 2:
                        done = True
                    break
                out = session.dispatch(name, a)
                trace.append({"step": row["steps"], "tool": name, "args": a,
                              "result": out[:2000]})
                if len(out) > cfg.max_tool_result_chars:
                    out = out[: cfg.max_tool_result_chars] + "\n...[truncated]"
                messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
            if done:
                break
    except Exception as e:
        row["status"] = f"error:{type(e).__name__}"
        row["why"] = str(e)[:300]
    finally:
        db.close()
    if args.trace_dir:
        d = Path(args.trace_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{iid}.json").write_text(json.dumps(
            {"instance_id": iid, "question": rec["question"], "db": rec["db"],
             "row": row, "trace": trace}, indent=1, default=str))
    return row


COLS = ["instance_id", "picked", "picked_correct", "parsed", "n_candidates",
        "n_correct_available", "steps", "salvaged", "own_steps", "own_ok",
        "tables_given", "status", "why"]


def read_done(path):
    """Rows already in the CSV, so a preempted job resumes instead of restarting.

    A CSV written by an older version of this script has a different header. Such
    a file is moved aside rather than half-read: its rows were produced by
    different code and must not be mixed into a new run's score.
    """
    f = Path(path)
    if not f.exists():
        return {}
    with open(f, newline="") as fh:
        rd = csv.DictReader(fh)
        if (rd.fieldnames or []) != COLS:
            bak = f.with_suffix(f.suffix + ".bak")
            f.replace(bak)
            print(f"[resume] {f.name} has an old header; moved to {bak.name}, "
                  "starting fresh", flush=True)
            return {}
        out = {}
        for r in rd:
            iid = r.get("instance_id")
            if not iid:
                continue
            r["picked_correct"] = str(r.get("picked_correct")) == "True"
            r["parsed"] = str(r.get("parsed")) == "True"
            for k in ("n_candidates", "n_correct_available", "steps", "salvaged"):
                r[k] = int(r.get(k) or 0)
            out[iid] = r
    return out


def score(rows, label):
    tot = {"all": 0, "mixed": 0, "none": 0}
    ok = {"all": 0, "mixed": 0, "none": 0}
    for r in rows:
        n, k = r["n_correct_available"], r["n_candidates"]
        cls = "all" if n == k and k else ("none" if n == 0 else "mixed")
        tot[cls] += 1
        ok[cls] += bool(r["picked_correct"])
    ach = tot["all"] + tot["mixed"]
    print(f"\n==== {label} ====")
    print(f"total           {sum(ok.values())}/{sum(tot.values())}")
    print(f"  all-correct   {ok['all']}/{tot['all']}")
    print(f"  MIXED         {ok['mixed']}/{tot['mixed']} = "
          f"{ok['mixed'] / max(tot['mixed'], 1):.4f}   <- the metric with signal")
    print(f"  none-correct  {ok['none']}/{tot['none']}")
    print(f"on {ach} achievable {ok['all'] + ok['mixed']}/{ach}")
    bad = [r for r in rows if not r["parsed"]]
    if bad:
        print(f"did not choose: {len(bad)} "
              f"({', '.join(sorted({r['status'] for r in bad}))})")
    if rows:
        print(f"steps: mean {sum(r['steps'] for r in rows) / len(rows):.1f} | "
              f"salvaged tool calls: {sum(r.get('salvaged', 0) for r in rows)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--preview-rows", type=int, default=12)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--instances", default=None, help="comma-separated subset")
    ap.add_argument("--achievable-only", action="store_true",
                    help="judge only questions where some candidate is correct "
                         "(pass@4 achievable). The questions where none is "
                         "correct score zero whatever the judge picks, so they "
                         "cost time and tell us nothing.")
    ap.add_argument("--shuffle-labels", action="store_true",
                    help="shuffle presentation order to break the A-preference")
    ap.add_argument("--schema-upfront", action="store_true",
                    help="put describe_table for the candidates' tables in the prompt")
    ap.add_argument("--max-tables", type=int, default=6)
    ap.add_argument("--diff-facts", action="store_true",
                    help="state the computed differences between candidate "
                         "results in the prompt (column widths, string-wrapped "
                         "numbers, rows that collapse under normalisation)")
    ap.add_argument("--scorer-note", action="store_true",
                    help="state the grading rule (extra columns are tolerated)")
    ap.add_argument("--independent-first", action="store_true",
                    help="answer the question first, without seeing any candidate")
    ap.add_argument("--trace-dir", default=None,
                    help="write one JSON trace per question (what it checked)")
    ap.add_argument("--resume", action="store_true",
                    help="keep rows already in --out and judge only the rest")
    args = ap.parse_args()

    cfg = AgentConfig(max_steps=args.max_steps, context_mode="full")
    data = json.load(open(args.inputs))
    if args.instances:
        want = {x.strip() for x in args.instances.split(",")}
        data = {k: v for k, v in data.items() if k in want}
    if args.achievable_only:
        n_all = len(data)
        data = {k: v for k, v in data.items()
                if any(c["correct"] for c in v["candidates"])}
        print(f"[achievable-only] {len(data)} of {n_all} questions have a correct "
              f"candidate; skipping the other {n_all - len(data)}", flush=True)

    done = read_done(args.out) if args.resume else {}
    # a row that errored out is worth retrying; a real choice is not
    done = {k: v for k, v in done.items() if v["parsed"]}
    items = sorted((k, v) for k, v in data.items() if k not in done)

    print(f"{len(data)} questions, {len(done)} already done, {len(items)} to judge, "
          f"{args.workers} workers, {args.max_steps} steps each", flush=True)

    # append as we go: on this partition the job can be preempted at any moment
    fresh = not Path(args.out).exists() or not done
    fh = open(args.out, "w" if fresh else "a", newline="")
    writer = csv.DictWriter(fh, fieldnames=COLS)
    if fresh:
        writer.writeheader()
        fh.flush()

    t0 = time.time()
    n_done = [0]

    from concurrent.futures import ThreadPoolExecutor

    def work(kv):
        r = judge_one(kv[0], kv[1], args, cfg)
        with _print_lock:
            n_done[0] += 1
            writer.writerow({k: r.get(k, "") for k in COLS})
            fh.flush()
            print(f"[{n_done[0]}/{len(items)}] {r['instance_id']:<10} "
                  f"{r['status']:<12} pick={r['picked'] or '-':<3} "
                  f"correct={r['picked_correct']} steps={r['steps']}", flush=True)
        return r

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            rows = list(ex.map(work, items))
    finally:
        fh.close()

    rows = list(done.values()) + rows
    score(rows, f"{args.model} with tools, {args.max_steps} steps")
    print(f"elapsed {(time.time() - t0) / 60:.1f} min -> {args.out}")


if __name__ == "__main__":
    main()
