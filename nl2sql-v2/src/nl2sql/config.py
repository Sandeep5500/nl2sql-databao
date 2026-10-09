from dataclasses import dataclass, field
from pathlib import Path

import os

# Data root: the directory containing Spider2/, spider2-dce/, and logs/.
# Defaults to the parent of this repo (the nl2sql-databao nested layout).
# Standalone clones set NL2SQL_DATA_ROOT, e.g. on Babel:
#   export NL2SQL_DATA_ROOT=/data/user_data/sandeep3/personal/nl2sql-databao
REPO_ROOT = Path(os.environ.get("NL2SQL_DATA_ROOT",
                                Path(__file__).resolve().parents[3]))
# NL2SQL_SPIDER2_LITE: use a Spider2 checkout elsewhere (e.g. when the submodule is empty)
SPIDER2_LITE = Path(os.environ.get("NL2SQL_SPIDER2_LITE", REPO_ROOT / "Spider2/spider2-lite"))
SQLITE_DIR = SPIDER2_LITE / "resource/databases/spider2-localdb"
DOCS_DIR = SPIDER2_LITE / "resource/documents"
QUESTIONS_FILE = SPIDER2_LITE / "spider2-lite.jsonl"
GOLD_EXEC_DIR = SPIDER2_LITE / "evaluation_suite/gold/exec_result"
GOLD_SQL_DIR = SPIDER2_LITE / "evaluation_suite/gold/sql"
EVAL_JSONL = SPIDER2_LITE / "evaluation_suite/gold/spider2lite_eval.jsonl"

# Retrieval indexes for the warehouse lanes, written by scripts/build_bq_context.py
# as <CONTEXT_DIR>/<engine>/<db>.npz. Defaults beside the DCE artifacts; on Modal it
# is set to the results volume, which is the writable one the builder commits and the
# benchmark shards read.
CONTEXT_DIR = Path(os.environ.get("NL2SQL_CONTEXT_DIR",
                                  REPO_ROOT / "spider2-dce/output"))

# Spider 2.0-Snow: the same 547 questions as lite, every database re-hosted on
# Snowflake. instance_ids are namespaced by origin -- sf_local### are twins of our
# local### SQLite questions, sf_bq### came from BigQuery (the enterprise-scale
# schemas), sf###/sf_ga### were natively Snowflake. Gold exec CSVs ship in-repo, so
# scoring is offline; only the agent's own queries need a live warehouse.
SPIDER2_SNOW = Path(os.environ.get("NL2SQL_SPIDER2_SNOW", REPO_ROOT / "Spider2/spider2-snow"))
SNOW_QUESTIONS_FILE = SPIDER2_SNOW / "spider2-snow.jsonl"
SNOW_DOCS_DIR = SPIDER2_SNOW / "resource/documents"
SNOW_GOLD_EXEC_DIR = SPIDER2_SNOW / "evaluation_suite/gold/exec_result"
SNOW_GOLD_SQL_DIR = SPIDER2_SNOW / "evaluation_suite/gold/sql"
SNOW_EVAL_JSONL = SPIDER2_SNOW / "evaluation_suite/gold/spider2snow_eval.jsonl"

# Spider 2.0-DBT: 69 dbt projects on DuckDB. Not text-to-SQL -- each instance is a
# project directory the agent must complete, scored by Spider2's own evaluator.
SPIDER2_DBT = Path(os.environ.get("NL2SQL_SPIDER2_DBT", REPO_ROOT / "Spider2/spider2-dbt"))
DBT_EXAMPLES_DIR = SPIDER2_DBT / "examples"
DBT_QUESTIONS_FILE = DBT_EXAMPLES_DIR / "spider2-dbt.jsonl"
DBT_EVAL_SUITE = SPIDER2_DBT / "evaluation_suite"

# Writable scratch for staged dbt project copies (never the pristine examples/).
SCRATCH_DIR = Path(os.environ.get("NL2SQL_SCRATCH", REPO_ROOT / "logs/scratch"))
DCE_PROJECT_DIR = REPO_ROOT / "spider2-dce"
VLLM_ENDPOINT_FILE = REPO_ROOT / "logs/vllm_endpoint.txt"

# Augmentation sources staged under dataset-augmentation/ (see that dir's README).
# Each has its own instances.jsonl + databases/ dir; no id-prefix filtering needed
# since those files are pure (unlike spider2-lite.jsonl, which mixes local/bigquery/
# snowflake ids and needs the "local" prefix filter below).
DATASET_AUGMENTATION_DIR = REPO_ROOT / "dataset-augmentation"


@dataclass
class DataSource:
    name: str
    questions_file: Path
    db_dir: Path
    docs_dir: Path | None = None
    id_prefix: str | None = None  # only include instance_ids with this prefix
    # several families can share one engine (lite's BigQuery lane is bq### and
    # ga###), so allow a set of accepted prefixes as well
    id_prefixes: tuple[str, ...] = ()
    # "every snow instance that is NOT a twin of our locals" needs exclusion as
    # well as inclusion; both filters apply.
    id_exclude_prefixes: tuple[str, ...] = ()
    dialect: str = "duckdb_sqlite"       # keys into prompts.DIALECTS
    # canonical key -> this source's key, applied at load time so the rest of
    # the harness only ever sees q["question"] / q["db"].
    field_map: dict[str, str] = field(default_factory=dict)
    gold_exec_dir: Path | None = None    # None -> module GOLD_EXEC_DIR
    eval_jsonl: Path | None = None       # None -> module EVAL_JSONL


DATA_SOURCES: dict[str, DataSource] = {
    "spider2": DataSource("spider2", QUESTIONS_FILE, SQLITE_DIR, DOCS_DIR,
                          id_prefix="local"),
    "bird_minidev": DataSource(
        "bird_minidev", DATASET_AUGMENTATION_DIR / "bird_minidev/instances.jsonl",
        DATASET_AUGMENTATION_DIR / "bird_minidev/databases"),
    "kaggledbqa": DataSource(
        "kaggledbqa", DATASET_AUGMENTATION_DIR / "kaggledbqa/instances.jsonl",
        DATASET_AUGMENTATION_DIR / "kaggledbqa/databases"),
    "spider_syn": DataSource(
        "spider_syn", DATASET_AUGMENTATION_DIR / "spider_syn/instances.jsonl",
        DATASET_AUGMENTATION_DIR / "spider_syn/databases"),
}

# Snowflake sources share everything but which instance_ids they admit.
# db_dir is unused for Snowflake (a connection, not a file, locates the data);
# it points at the suite root so the dataclass contract stays simple.
_SNOW_COMMON = dict(questions_file=SNOW_QUESTIONS_FILE, db_dir=SPIDER2_SNOW,
                    docs_dir=SNOW_DOCS_DIR, dialect="snowflake",
                    field_map={"question": "instruction", "db": "db_id"},
                    gold_exec_dir=SNOW_GOLD_EXEC_DIR,
                    eval_jsonl=SNOW_EVAL_JSONL)

# spider2-lite's non-local instances, which is where the BigQuery and Snowflake
# questions actually live. Engine is implied by the id family, verified against
# resource/databases/<engine>/ for all 547 instances with zero unmapped:
#   bq### (180) + ga### (25) -> BigQuery   = 205
#   sf### (18) + sf_bq### (189) -> Snowflake = 207
# (the repo README says 214/198; the data says 205/207.)
# Gold exec CSVs and the eval jsonl are lite's own, i.e. the module defaults.
_LITE_COMMON = dict(questions_file=QUESTIONS_FILE, db_dir=SQLITE_DIR,
                    docs_dir=DOCS_DIR)

DATA_SOURCES |= {
    "spider2_lite_bq": DataSource("spider2_lite_bq", id_prefixes=("bq", "ga"),
                                 dialect="bigquery", **_LITE_COMMON),
    "spider2_lite_sf": DataSource("spider2_lite_sf", id_prefix="sf",
                                  dialect="snowflake", **_LITE_COMMON),
}
DATA_SOURCES |= {
    # the target: every snow question we have never run (412 of 547)
    "spider2_snow_new": DataSource("spider2_snow_new",
                                   id_exclude_prefixes=("sf_local",), **_SNOW_COMMON),
    # BigQuery-origin only (214): the enterprise-scale schemas
    "spider2_snow_bq": DataSource("spider2_snow_bq", id_prefix="sf_bq", **_SNOW_COMMON),
    # natively-Snowflake only (198)
    "spider2_snow_native": DataSource(
        "spider2_snow_native", id_exclude_prefixes=("sf_local", "sf_bq"), **_SNOW_COMMON),
    # twins of our 135 locals -- a control arm, not the target
    "spider2_snow_control": DataSource("spider2_snow_control", id_prefix="sf_local",
                                       **_SNOW_COMMON),
    "spider2_snow_all": DataSource("spider2_snow_all", **_SNOW_COMMON),
    # dbt: scored by Spider2's own evaluator, so no gold_exec_dir/eval_jsonl here
    "spider2_dbt": DataSource("spider2_dbt", DBT_QUESTIONS_FILE, DBT_EXAMPLES_DIR,
                              dialect="duckdb",
                              field_map={"question": "instruction"}),
}


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str = field(default_factory=lambda: os.environ.get("VLLM_API_KEY", "EMPTY"))
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: float = 180.0
    # vLLM chat_template_kwargs, e.g. {"enable_thinking": False} for Qwen
    chat_template_kwargs: dict = field(default_factory=dict)


@dataclass
class CriticConfig:
    enabled: bool = False
    base_url: str | None = None  # defaults to actor endpoint if None
    model: str | None = None
    max_rounds: int = 2
    temperature: float = 0.0
    max_tokens: int = 1024
    chat_template_kwargs: dict = field(default_factory=dict)


@dataclass
class AgentConfig:
    max_steps: int = 30                 # LLM turns per episode
    preview_rows_default: int = 12
    preview_rows_max: int = 50
    result_rows_max: int = 5000     # full stored result cap (max gold is 2000 rows)
    cell_char_limit: int = 1024
    search_limit: int = 8               # chunks returned per search_context call
    expansion_queries: int = 3          # 0 disables query expansion
    # Calibrated on real traces: tool-heavy content tokenizes at ~2.7 chars/token,
    # so 100K chars ≈ 37K tokens — safe headroom under 60K ctx minus 4K output.
    history_char_budget: int = 100_000
    truncated_tool_msg_chars: int = 600
    max_tool_result_chars: int = 16_000  # single tool result cap at insertion
    keep_recent_turns: int = 5           # turns kept verbatim by memory compaction
    summary_max_tokens: int = 700        # [MEMORY] note budget
    find_value_max_columns: int = 200
    context_mode: str = "search"        # search | full | oracle  (ablation arms A/B/C)
    text_sql_fallback: bool = False     # execute ```sql blocks from non-tool models
    dbt_timeout_s: float = 600.0        # per `dbt build` invocation
