# Dataset augmentation staging area

Candidate data sources for growing the Spider2.0-Lite benchmark. 

DCE and the harness's execution/scoring path are dialect-agnostic and SQLite-compatible as-is.

Each `<source>/` directory:
- `databases/*.sqlite`: real SQLite database files

- `instances.jsonl`: one question per line: `instance_id`, `db`, `question`, `external_knowledge`, `gold_sql` and dataset-specific extras like `evidence`/`difficulty` for BIRD, `original_question` for Spider-Syn.

| Source | DBs | Questions | Gold SQL | Sources |
|---|---|---|---|---|
| `bird_minidev/` | 11 | 500 | inline | DBs+questions: `bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip` (mirrors https://github.com/bird-bench/mini_dev) |
| `kaggledbqa/` | 8 | 272 | inline | DBs: Google Drive folder linked from https://github.com/Chia-Hsuan-Lee/KaggleDBQA; questions: `examples/*.json` in that repo |
| `spider_syn/` | 20 | 1034 | inline | DBs: Spider 1.0 dev split (Google Drive, linked from https://yale-lily.github.io/spider); questions: `Spider-Syn/dev.json` from https://github.com/ygan/Spider-Syn |

## Status

- Done: DB files fetched, questions normalized into the harness's `instance_id`/`db`/`question` shape, gold SQL captured inline.


- Not done yet: DCE enrichment YAMLs.

__

---

# NL2SQL Dataset Augmentation Survey

2026-09-18

## Goal

- The NL2SQL harness (`nl2sql-v2`) currently benchmarks our tool-calling agent against Spider 2.0-Lite's local split: 135 natural-language questions over ~30 SQLite databases.
- It is scored by comparing execution results against gold CSVs.
- Previously we planned to grow our benchmark beyond this. For this purpose, we have surveyed publicly available NL2SQL datasets that ship a **real database with NL questions.**
- **We have also tried to select ones that have gold SQL** and checked whether they're actually compatible with our retrieval layer.

## Chosen sources

| Dataset | Dialect / DBs | Gold SQL? | Real DB shipped? | Scale | Why it's useful |
|---|---|---|---|---|---|
| **BIRD-SQL (Mini-Dev)** | SQLite, 11 DBs | Yes | Yes, real `.sqlite` files | 500 questions | Adds messier real-world data, plus "evidence" hint strings the model can be given as external knowledge. |
| **KaggleDBQA** | SQLite, 8 real Kaggle DBs | Yes | Yes, real `.sqlite` files | 272 questions | Tiny integration cost, real-world (non-academic) naming conventions. Complements Spider2's cleaner academic schemas. |
| **Spider-Syn** | SQLite, synonym-substituted questions | Yes (SQL reused from Spider 1.0, remapped to the perturbed question text) | Reuses Spider 1.0's DB files | 1,034 questions | Stresses paraphrase/schema-linking robustness. A different failure mode than raw generation difficulty. |

**Combined: 1,806 new questions across 39 databases**, roughly 13x the size of the current 135-question benchmark.

## Candidates considered and excluded

- **[Spider 1.0 (raw)](https://yale-lily.github.io/spider)**: Excluded as a standalone source since it's redundant with Spider2's own lineage (same author group, same schema conventions).
- **[WikiSQL](https://huggingface.co/datasets/Salesforce/wikisql)**: Gold SQL is too trivial (single-table SELECTs, no joins); widely flagged in the literature as saturated/noisy. Would dilute question difficulty rather than add value.
- **[CoSQL](https://yale-lily.github.io/cosql)**: Add multi-turn dialogue complexity on top of Spider's existing DBs, not new domains or data.
- **[EHRSQL](https://github.com/glee4810/EHRSQL)**: Requires PhysioNet credentialing to access, ships de-identified/shuffled values (poor for realistic value semantics), and has an "unanswerable question" concept our eval schema doesn't currently support.
- **[CSpider](https://taolusi.github.io/CSpider-explorer/)/[DuSQL](https://aclanthology.org/2020.emnlp-main.562/) and non-SQL-target ([NL2GQL](https://github.com/zhiqix/NL2GQL))**: Out of scope (?) for an English, SQL-target benchmark.

## Compatibility with our Retrieval Layer (or context-engine)

**Databao-context-engine is dialect-agnostic by design, not SQLite-specific.**

- It has a plugin architecture with one directory per database engine
  - `sqlite`, `postgresql`, `mysql`, `bigquery`, `snowflake`, `duckdb`, `mssql`, `athena`, `clickhouse`
- Each implements a shared `BaseConnector`/`BaseIntrospector` interface.
- SQLite-specific code is isolated to the sqlite plugin.
- The enriched schema YAML output stores the dialect as a plain tag
- The actual schema tree (catalogs/schemas/tables/columns) is dialect-neutral — same shape regardless of engine.
- However, since all three chosen sources are SQLite, DCE enrichment should work as expected without needing new code.

## Compatibility with the harness's execution and scoring path compatible?

- The harness loads each question as `instance_id` / `db` / `question` / optional `external_knowledge`
- Executes SQL through DuckDB's SQLite scanner (`ATTACH '<path>' AS db (TYPE sqlite, READ_ONLY)`)
- Scores by diffing the resulting table against a gold execution CSV — a comparison that only cares about the resulting data.
- Since all three new sources are plain SQLite files, they should fit into this exact same path.

## Work completed so far

All three sources have been downloaded.

```
dataset-augmentation/
  bird_minidev/   11 databases (1.4 GB), 500 questions, gold SQL inline
  kaggledbqa/     8 databases (378 MB), 272 questions, gold SQL inline
  spider_syn/     20 databases (102 MB), 1,034 questions, gold SQL inline
```

- Each `instances.jsonl` match the harness's expected question shape (`instance_id`, `db`, `question`, `external_knowledge`)
- The gold SQL is captured as an extra field.
- Combined multi-source loading.
  - **`nl2sql-v2/scripts/run_benchmark.py`**: `load_questions()` now takes a list of sources and can merge multiple of them.
  - A `--source` flag was added. `db_path`/`external_knowledge` resolution now uses each question's own `_db_dir`/`_docs_dir` instead of the hardcoded Spider2 globals.
  - New usage, e.g.:
    ```bash
    uv run python scripts/run_benchmark.py --source bird_minidev --instances bird_1471,bird_1472
    ```
    Note: currently running the new sources today will execute fine but score `0 (no_gold_files)` since gold exec CSVs haven't been generated yet and `search_context` will be disabled for their DBs until DCE enrichment runs too.
- **Gold execution-result CSVs**: Ran each gold SQL query by capturing its output as a CSV, in the same format the scorer already expects.

## Remaining work

- **DCE enrichment**: Add one `type: sqlite` config YAML per new database and run the enrichment script to build the semantic schema index (`dce.duckdb`).
  - Same process already used for the existing 30 databases
  - The enrichment script itself calls the vLLM model, so it needs the cluster.
- Determining improvements that can be made to the existing context engine. The llm enrichment quality is currently very poor for a lot of columns, lots of very generic stuff. We can include better things to enrich with from KTX context engine.
