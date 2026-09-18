from dataclasses import dataclass, field
from pathlib import Path

import os

# Data root: the directory containing Spider2/, spider2-dce/, and logs/.
# Defaults to the parent of this repo (the nl2sql-databao nested layout).
# Standalone clones set NL2SQL_DATA_ROOT, e.g. on Babel:
#   export NL2SQL_DATA_ROOT=/data/user_data/sandeep3/personal/nl2sql-databao
REPO_ROOT = Path(os.environ.get("NL2SQL_DATA_ROOT",
                                Path(__file__).resolve().parents[3]))
SPIDER2_LITE = REPO_ROOT / "Spider2/spider2-lite"
SQLITE_DIR = SPIDER2_LITE / "resource/databases/spider2-localdb"
DOCS_DIR = SPIDER2_LITE / "resource/documents"
QUESTIONS_FILE = SPIDER2_LITE / "spider2-lite.jsonl"
GOLD_EXEC_DIR = SPIDER2_LITE / "evaluation_suite/gold/exec_result"
GOLD_SQL_DIR = SPIDER2_LITE / "evaluation_suite/gold/sql"
EVAL_JSONL = SPIDER2_LITE / "evaluation_suite/gold/spider2lite_eval.jsonl"
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


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str = "EMPTY"
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
