#!/usr/bin/env python3
"""Index ONE already-enriched datasource into dce.duckdb -- embeddings only, no LLM.

The expensive half of DCE setup (the per-column descriptions) is already committed under
spider2-dce/output/databases/*.yaml. Only the vector index (spider2-dce/output/dce.duckdb,
1.2GB, gitignored) has to be rebuilt, and that needs nothing but the embedding model.

    uv run --project ../nl2sql-v2 python ../scripts/index_one_db.py \
        --datasource databases/music.yaml --embed-host 127.0.0.1 --embed-port 11434 \
        --dce-dir .

Differences from enrich_one_db.py: should_enrich_context=False, and the description
provider raises if anything asks it for a description -- so a silent re-enrichment with
the wrong model cannot happen. If this script fails with EnrichmentAttempted, the enriched
YAML for that datasource is missing or stale and enrich_one_db.py (which needs a served
vLLM) is the right tool for it.

A note on the timeout: DCE's OllamaConfig defaults to 120s per request and reports a
failure as "timed out after Nones" (it prints the unset per-call parameter, not the
config value that was actually used). Embedding a large table on CPU exceeds 120s, so
--embed-timeout defaults to 1800 here and ollama should have a GPU.

Writers are exclusive: DuckDB allows one writer per file, so run datasources
SEQUENTIALLY against one --dce-dir, or give each parallel worker its own --dce-dir and
merge afterwards (scripts/merge_dce_indexes.py).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("index_one_db")


class EnrichmentAttempted(RuntimeError):
    """Raised if the build asks for a description: the enriched YAML is missing."""


class RefusingDescriptionProvider:
    """A description provider that must never be called."""

    def __getattr__(self, name):
        def _refuse(*args, **kwargs):
            raise EnrichmentAttempted(
                f"the build called description_provider.{name}(): this datasource has no "
                f"usable enriched YAML, so it needs enrich_one_db.py and a served vLLM")
        return _refuse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasource", required=True, help="e.g. databases/music.yaml")
    ap.add_argument("--embed-host", default="127.0.0.1")
    ap.add_argument("--embed-port", type=int, default=11434)
    ap.add_argument("--dce-dir", type=Path, default=Path("."))
    ap.add_argument("--embed-timeout", type=float, default=1800.0,
                    help="seconds per /api/embed request (default 1800; the DCE default of "
                         "120 is not enough for a large table on CPU)")
    args = ap.parse_args()

    from databao_context_engine.build_sources.build_runner import build
    from databao_context_engine.build_sources.build_service import BuildService
    from databao_context_engine.datasources.types import DatasourceId
    from databao_context_engine.llm.config import OllamaConfig
    from databao_context_engine.llm.embeddings.ollama import OllamaEmbeddingProvider
    from databao_context_engine.llm.service import OllamaService
    from databao_context_engine.plugins.plugin_loader import DatabaoContextPluginLoader
    from databao_context_engine.project.layout import ensure_project_dir
    from databao_context_engine.services.factories import create_chunk_embedding_service
    from databao_context_engine.storage.connection import open_duckdb_connection
    from databao_context_engine.storage.migrate import migrate

    project_layout = ensure_project_dir(project_dir=args.dce_dir)
    plugin_loader = DatabaoContextPluginLoader()

    embed_service = OllamaService(config=OllamaConfig(
        host=args.embed_host, port=args.embed_port, bin_path="ollama",
        timeout=args.embed_timeout))
    embedding_provider = OllamaEmbeddingProvider(
        service=embed_service,
        model_details=project_layout.project_config.ollama_embedding_model_details)

    db_path = project_layout.db_path
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        migrate(db_path)

    ds_id = DatasourceId.from_string_repr(args.datasource)
    with open_duckdb_connection(db_path) as conn:
        build_service = BuildService(
            project_layout=project_layout,
            chunk_embedding_service=create_chunk_embedding_service(
                conn, embedding_provider=embedding_provider),
            plugin_loader=plugin_loader,
            description_provider=RefusingDescriptionProvider())
        t0 = time.monotonic()
        results = build(project_layout=project_layout, build_service=build_service,
                        datasource_ids=[ds_id], should_index=True,
                        should_enrich_context=False)
        elapsed = (time.monotonic() - t0) / 60

    statuses = [(str(r.datasource_id), str(r.status), r.error) for r in results]
    logger.info("done in %.1f min: %s", elapsed, statuses)
    bad = [s for s in statuses if "OK" not in s[1].upper()]
    if bad:
        logger.error("not OK: %s", bad)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
