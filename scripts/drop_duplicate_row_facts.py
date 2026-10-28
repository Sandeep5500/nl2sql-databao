#!/usr/bin/env python3
"""Remove facts about whole duplicate rows from the explored notes.

Stated even as plain facts ("6,838 rows are exact copies of another row"),
these made the model deduplicate where the benchmark's answers count every
row: local065 went from 10 of 12 correct runs without the notes to 1 of 8 with
them. Notes about non-unique *values* in a column are kept. Matching notes get
`excluded: "duplicate-rows"`; matching sentences are cut from table and
database texts (originals kept in `*_with_duplicates`).

Usage (from repo root): uv run --project nl2sql-v2 python scripts/drop_duplicate_row_facts.py
"""

import json
import re
from pathlib import Path

NOTES = Path(__file__).resolve().parents[1] / "spider2-dce" / "output" / "notes"
DUP = re.compile(r"exact(ly)?[ -](duplicate|cop(y|ies)|same row)|duplicate rows|duplicated rows"
                 r"|identical rows|rows (that )?are (exact )?(copies|duplicates)"
                 r"|cop(y|ies) of another row|fully identical|duplicate (entries|records)", re.I)


def strip_sentences(text: str) -> str:
    kept = [s for s in re.split(r"(?<=\.)\s+", text or "") if not DUP.search(s)]
    return " ".join(kept).strip()


def main():
    total = 0
    for path in sorted(NOTES.glob("*.json")):
        doc = json.loads(path.read_text())
        n = 0
        for rec in doc["tables"].values():
            for x in (rec.get("column_notes") or []) + (rec.get("pitfalls") or []):
                if x.get("fact") and DUP.search(x["fact"]):
                    x["excluded"] = "duplicate-rows"
                    n += 1
            tf = rec.get("table_fact")
            if tf and DUP.search(tf):
                rec["table_fact_with_duplicates"] = tf
                rec["table_fact"] = strip_sentences(tf)
                n += 1
        df = doc.get("database_fact")
        if df and DUP.search(df):
            doc["database_fact_with_duplicates"] = df
            doc["database_fact"] = strip_sentences(df)
            n += 1
        if n:
            path.write_text(json.dumps(doc, indent=1, default=str))
            print(f"{path.stem}: {n} removed")
        total += n
    print(f"{total} duplicate-row facts removed")


if __name__ == "__main__":
    main()
