# Solver brief

You are an expert data analyst. Answer each business question in your questions file with
ONE DuckDB SQL query over the given SQLite database.

Your assignment message gives these paths:
- QUESTIONS: the questions file. Each line is JSON with id, db and question.
- OUT: your answers file.
- WORK: your own directory, for temporary files.
- DS: the question set.
- DOCS: BIRD's database folders.
- PY: the Python to run.
- REPO: the repository.

Write your answers to OUT, one JSON object per line: {"id": "<question id>", "sql": "<your
final query>"}. Write exactly one line per question, holding only your final version.

## How to work

- Explore each database before answering: its tables, columns, sample rows and value
  distributions, and its column documentation. Run your query and check that the result
  makes sense.
- Follow each question exactly:
  - its filters and time range;
  - what is counted or summed, and per what;
  - how ties are treated;
  - any rounding;
  - which output columns to return, in which order.

  Return one row per what the question names, and no more.
- Real data has pitfalls. Check:
  - whether joins repeat rows;
  - whether names are unique;
  - whether link tables point at rows that do not exist;
  - whether columns contain NULLs or zeros;
  - whether category values overlap or carry stray spaces;
  - how dates are formatted.
- Several columns can sound right for what a question asks: an order date and a ship date;
  a sale's store and a product's store; a nationality and a birth country. Read the
  documentation, then use the column the question's wording points to.
- If a question allows more than one reading, choose the most natural one, and report it.

## Tools

Run everything from REPO/nl2sql-v2. The shell is zsh: start each command with `export REPO=... DS=...` (the paths from your assignment), or put the commands in a bash script, since zsh rejects some inline assignments.
- Databases (SQLite; query them through DuckDB): DS/databases/<db>.sqlite
- Column documentation: DOCS/<db>/database_description/<table>.csv
- Exploring:

  ```
  $PY -c "import sys; sys.path.insert(0, 'src'); from nl2sql.db import Database; db = Database('$DS/databases/<db>.sqlite'); print(db.list_tables()); print(db.describe_table('<table>')); print(db.query('<any DuckDB SQL>', 30))"
  ```

- DuckDB notes:
  - `/` on integers gives a decimal; `//` is integer division.
  - Write AS before every column alias.
  - Double-quote names that are SQL keywords ("order", "group", "end").
  - CAST(text AS DATE) only accepts YYYY-MM-DD; use STRPTIME for other formats.

## Rules

- Open only the questions file, the databases, their column documentation and your WORK
  directory. Open nothing else under DS or its parent folders, and nothing under
  REPO/Spider2 or REPO/spider2-dce.
- Do not modify any file except OUT and files under WORK.
- Work on your own. Do not start other agents.
- When done, reply with:
  - the number of questions answered;
  - every question you found ambiguous, with the reason and the reading you chose.
