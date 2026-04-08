#!/usr/bin/env python3
"""Experiment: critique pass on a single DCE-enriched table.

Loads one table from an already-enriched DCE YAML, sends its current column
descriptions + sample rows to the LLM, asks for targeted rewrites of any
ambiguous descriptions, and logs the diff. Does NOT modify the YAML.

Usage:
    uv run python scripts/experiment_critique_enrich.py \\
        --yaml spider2-dce/output/databases/baseball.yaml \\
        --table player \\
        --vllm-host babel-s9-24 --vllm-port 8765

The script reads the vLLM endpoint from logs/vllm_endpoint.txt if no host/port
is supplied.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("critique_experiment")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Prompt ────────────────────────────────────────────────────────────────────

CRITIQUE_PROMPT = """You are refining column descriptions for a database table \
so that a SQL-writing agent can pick the correct column without guessing.

TABLE: {table_name}
SCHEMA: {schema_name}

COLUMNS (with current draft descriptions and sample values):
{columns_block}

TASKS:
  1. For any column whose CURRENT description does not clearly distinguish it
     from sibling columns in this table, rewrite its description to include:
     - How it differs from similarly-named or similarly-purposed columns
     - When a query would use this column vs an alternative
  2. If a column has a clear relationship to another column — a foreign-key
     name match, a matching prefix/suffix pair (e.g. start_date/end_date), or
     an identical sequence of sample values — mention the related column by
     name in the description. Do NOT invent relationships that are not visible
     in the column names or sample values shown above.

MANDATORY SAMPLE CITATION RULE:
  If the sample_values shown above for a column are DIFFERENT from the sample
  values of any sibling column you compare it to, you MUST quote at least one
  concrete sample value from BOTH columns inside the rewritten description
  (e.g. `name_given` holds the full given name like "David Allan", whereas
  `name_first` holds only the first name like "David").
  If you rewrite one column in a group of siblings, you must also rewrite
  every other column in that group so the disambiguation is symmetric.

Leave any column whose current description is already unambiguous untouched.
Return ONLY YAML with a single `rewrites` key, listing ONLY the columns you
changed. Every `name` must match a column from the input exactly.

Example output format:
rewrites:
  - name: <exact column name>
    description: <new description, 1-3 sentences>
  - name: <another column name>
    description: <another new description>

If no columns need rewriting, return:
rewrites: []

Return only the YAML. No preamble, no code fences, no commentary."""


# ── Helpers ───────────────────────────────────────────────────────────────────


def load_endpoint_fallback() -> tuple[str, int, str]:
    """Read logs/vllm_endpoint.txt to discover host/port/model."""
    f = REPO_ROOT / "logs" / "vllm_endpoint.txt"
    if not f.exists():
        raise SystemExit("No vllm_endpoint.txt and no --vllm-host provided.")
    lines = f.read_text().strip().split("\n")
    host, _, port = lines[0].partition(":")
    model = "unknown"
    for line in lines[1:]:
        if line.startswith("Model:"):
            model = line.split(":", 1)[1].strip()
    return host, int(port), model


def load_table(yaml_path: Path, table_name: str) -> tuple[dict, str]:
    """Load a single table dict + parent schema name from an enriched DCE YAML."""
    with yaml_path.open() as f:
        doc = yaml.safe_load(f)
    for catalog in doc["context"]["catalogs"]:
        for schema in catalog.get("schemas", []):
            for table in schema.get("tables", []):
                if table["name"] == table_name:
                    return table, schema["name"]
    raise SystemExit(f"Table {table_name!r} not found in {yaml_path}")


def build_columns_block(table: dict, max_sample_values: int = 5) -> str:
    """Format columns + per-column sample values for the prompt."""
    samples = table.get("samples", []) or []
    lines: list[str] = []
    for col in table["columns"]:
        name = col["name"]
        ctype = col.get("type", "UNKNOWN")
        desc = (col.get("description") or "").strip().replace("\n", " ")
        # Collect up to max_sample_values distinct sample values for this column
        seen: list[str] = []
        for row in samples:
            if name in row and row[name] is not None and row[name] != "":
                val = str(row[name])
                if val not in seen:
                    seen.append(val)
                if len(seen) >= max_sample_values:
                    break
        sample_str = ", ".join(seen) if seen else "(none)"
        lines.append(f"  - name: {name}")
        lines.append(f"    type: {ctype}")
        lines.append(f"    current_description: {desc}")
        lines.append(f"    sample_values: [{sample_str}]")
    return "\n".join(lines)


def call_vllm(base_url: str, model: str, prompt: str, max_tokens: int = 2048) -> str:
    """Single non-streaming chat completion against vLLM."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    log.info("POST %s/v1/chat/completions  (model=%s, max_tokens=%d)", base_url, model, max_tokens)
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    choice = data["choices"][0]
    finish = choice.get("finish_reason")
    content = choice["message"]["content"]
    usage = data.get("usage", {})
    log.info(
        "response: finish_reason=%s  prompt_tokens=%s  completion_tokens=%s",
        finish, usage.get("prompt_tokens"), usage.get("completion_tokens"),
    )
    if finish == "length":
        log.warning("HIT max_tokens — output may be truncated")
    return content


def extract_yaml(raw: str) -> str:
    """Strip code fences / thinking tags if the model added them despite instructions."""
    # Drop <think>...</think> blocks (GLM sometimes emits these)
    raw = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL)
    # Drop ```yaml / ``` fences
    raw = re.sub(r"^```(?:yaml|yml)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    return raw.strip()


def parse_rewrites(raw: str) -> list[dict]:
    cleaned = extract_yaml(raw)
    try:
        parsed = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        log.error("YAML parse failed: %s", e)
        log.error("Raw content (first 1000 chars):\n%s", cleaned[:1000])
        return []
    if not isinstance(parsed, dict) or "rewrites" not in parsed:
        log.error("Response missing `rewrites` key. Got: %s", type(parsed).__name__)
        log.error("Parsed content: %s", parsed)
        return []
    rewrites = parsed["rewrites"] or []
    if not isinstance(rewrites, list):
        log.error("`rewrites` is not a list: %s", type(rewrites).__name__)
        return []
    return rewrites


def validate_and_diff(
    table: dict, rewrites: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Return (valid_rewrites, invalid_entries) — valid ones have real column names."""
    valid_names = {c["name"] for c in table["columns"]}
    valid: list[dict] = []
    invalid: list[dict] = []
    for entry in rewrites:
        if not isinstance(entry, dict):
            invalid.append({"reason": "not-a-dict", "entry": entry})
            continue
        name = entry.get("name")
        new_desc = entry.get("description")
        if name not in valid_names:
            invalid.append({"reason": "unknown-column", "entry": entry})
            continue
        if not isinstance(new_desc, str) or not new_desc.strip():
            invalid.append({"reason": "missing-description", "entry": entry})
            continue
        valid.append({"name": name, "description": new_desc.strip()})
    return valid, invalid


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", type=Path,
                    default=REPO_ROOT / "spider2-dce/output/databases/baseball.yaml")
    ap.add_argument("--table", default="player")
    ap.add_argument("--vllm-host", default=None)
    ap.add_argument("--vllm-port", type=int, default=None)
    ap.add_argument("--vllm-model", default=None)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--save-prompt", type=Path, default=None,
                    help="Write the critique prompt to this file for inspection.")
    ap.add_argument("--save-response", type=Path, default=None,
                    help="Write the raw LLM response to this file.")
    args = ap.parse_args()

    # Resolve vLLM endpoint
    if args.vllm_host and args.vllm_port:
        host, port = args.vllm_host, args.vllm_port
        model = args.vllm_model or load_endpoint_fallback()[2]
    else:
        host, port, discovered_model = load_endpoint_fallback()
        model = args.vllm_model or discovered_model
    base_url = f"http://{host}:{port}"
    log.info("vLLM endpoint: %s  model=%s", base_url, model)

    # Load the table
    table, schema_name = load_table(args.yaml, args.table)
    log.info("Loaded table %s (%d columns, %d sample rows)",
             args.table, len(table["columns"]), len(table.get("samples") or []))

    # Build prompt
    columns_block = build_columns_block(table)
    prompt = CRITIQUE_PROMPT.format(
        table_name=args.table,
        schema_name=schema_name,
        columns_block=columns_block,
    )
    log.info("Prompt size: %d chars (~%d tokens)", len(prompt), len(prompt) // 4)
    if args.save_prompt:
        args.save_prompt.write_text(prompt)
        log.info("Wrote prompt to %s", args.save_prompt)

    # Call vLLM
    raw = call_vllm(base_url, model, prompt, max_tokens=args.max_tokens)
    if args.save_response:
        args.save_response.write_text(raw)
        log.info("Wrote raw response to %s", args.save_response)

    # Parse
    rewrites = parse_rewrites(raw)
    valid, invalid = validate_and_diff(table, rewrites)

    log.info("")
    log.info("=" * 70)
    log.info("RESULTS")
    log.info("=" * 70)
    log.info("Columns in table        : %d", len(table["columns"]))
    log.info("Rewrites proposed       : %d", len(rewrites))
    log.info("Valid rewrites          : %d", len(valid))
    log.info("Invalid entries dropped : %d", len(invalid))
    if invalid:
        for inv in invalid:
            log.warning("  dropped (%s): %s", inv["reason"], inv["entry"])

    # Print per-column diff
    current = {c["name"]: (c.get("description") or "").strip().replace("\n", " ")
               for c in table["columns"]}
    print()
    print("=" * 70)
    print(f"DIFF  (table: {args.table})")
    print("=" * 70)
    if not valid:
        print("(no valid rewrites produced)")
    for entry in valid:
        name = entry["name"]
        print(f"\n── {name} ──")
        print(f"  BEFORE: {current[name]}")
        print(f"  AFTER : {entry['description']}")

    # Print summary of untouched columns
    touched = {e["name"] for e in valid}
    untouched = [c["name"] for c in table["columns"] if c["name"] not in touched]
    print()
    print(f"Untouched columns ({len(untouched)}): {', '.join(untouched)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
