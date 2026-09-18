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


- Not done yet: DCE enrichment YAMLs, gold execution-result CSVs (`evaluation_suite/gold/exec_result/*.csv`-style) and wiring these into `run_benchmark.py`'s instance loader.
