# Reviewer brief

You are the final reviewer for disputed items in a text-to-SQL training dataset. Each item is
a business question about a SQLite database (queried through DuckDB), with a gold SQL answer
written by one analyst. A second analyst who saw only the question wrote an independent
solution, and the two disagree in one of two ways:
- the solution's result differs from the gold's on the real data; or
- both give the same result on the real data, but different results on a slightly altered
  copy of the database (rows deleted, numbers nudged, values blanked, or new entities added).
  That means the two queries encode different interpretations that happen to coincide on the
  current data.

Your assignment message gives these paths:
- PACKETS: the packets file, in JSON lines. Each packet holds:
  - id, db, kind, question;
  - why_disputed;
  - gold_sql and gold_result (its first rows);
  - solutions: a list of {sql, result}.
- OUT: your verdicts file.
- WORK: your own directory, for temporary files.
- DS: the question set.
- DOCS: BIRD's database folders.
- PY: the Python to run.
- REPO: the repository.

For each packet, decide one of:
- **gold_right**: read carefully and naturally, the question asks for exactly what the gold
  computes. The solution misread it, made an error, or differs only in a way the question
  rules out.
- **gold_wrong**: the gold does not answer the question as written. Include the corrected
  SQL: use the solution's SQL if it is right, otherwise write your own.
- **ambiguous**: the question allows more than one reasonable reading, and the gold and the
  solution follow different reasonable ones.

For an alteration-only disagreement, ask which result the question, as written, would ask
for if the data did contain such rows:
- If the question settles it and the gold follows it, the gold is right.
- If the question settles it and the gold does not follow it, the gold is wrong, even if the
  current data hides the difference.
- If the question does not settle it and both readings are reasonable, the item is
  ambiguous.
- If the question does not settle it, but the current data makes the difference impossible
  and the gold is correct on the real data, prefer gold_right, and say so in the note.

For a lookalike_columns or grain item, check that the question's wording settles which
column, or which level and shape, is meant. If it does not, the item is ambiguous.

Investigate before deciding:
- Run both queries.
- Look at the relevant rows and the column documentation.
- Judge the question as written, not what its writer probably meant.

## Tools

Run everything from REPO/nl2sql-v2. The shell is zsh: start each command with `export REPO=... DS=...` (the paths from your assignment), or put the commands in a bash script, since zsh rejects some inline assignments.
- Databases: DS/databases/<db>.sqlite
- Column documentation: DOCS/<db>/database_description/<table>.csv
- Exploring:

  ```
  $PY -c "import sys; sys.path.insert(0, 'src'); from nl2sql.db import Database; db = Database('$DS/databases/<db>.sqlite'); print(db.describe_table('<table>')); print(db.query('<DuckDB SQL>', 30))"
  ```

## Output

Write one JSON object per line to OUT:

```
{"id": "...", "verdict": "gold_right|gold_wrong|ambiguous", "note": "<one or two sentences>", "fixed_sql": "<only if gold_wrong>", "suggested_question": "<only if ambiguous: a natural rewording that makes the gold's reading the only reasonable one>"}
```

## Rules

- Open only the packets file, the databases, their column documentation and your WORK
  directory. Open nothing else under DS or its parent folders, and nothing under
  REPO/Spider2 or REPO/spider2-dce.
- Do not modify any file except OUT and files under WORK.
- Work on your own. Do not start other agents.
- When done, reply with each verdict and a one-line reason.
