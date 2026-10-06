#!/usr/bin/env python3
"""Enrich + index a SINGLE datasource (unlike enrich_dce.py which sweeps all).

Usage (from spider2-dce/):
    uv run --project ../nl2sql-v2 python ../scripts/enrich_one_db.py \
        --datasource databases/oracle_sql.yaml \
        --vllm-host babel-n5-20 --vllm-port 8765 --vllm-model Qwen/Qwen3.5-9B \
        --embed-host babel-n5-20 --embed-port 11434 --dce-dir .
"""

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("enrich_one_db")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_dce import VLLMDescriptionProvider  # reuse the description provider


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasource", required=True, help="e.g. databases/oracle_sql.yaml")
    ap.add_argument("--vllm-host", required=True)
    ap.add_argument("--vllm-port", type=int, default=8765)
    ap.add_argument("--vllm-model", required=True)
    ap.add_argument("--embed-host", default="127.0.0.1")
    ap.add_argument("--embed-port", type=int, default=11434)
    ap.add_argument("--dce-dir", type=Path, default=Path("."))
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
        host=args.embed_host, port=args.embed_port, bin_path="ollama", timeout=120.0))
    embedding_provider = OllamaEmbeddingProvider(
        service=embed_service,
        model_details=project_layout.project_config.ollama_embedding_model_details)

    desc_provider = VLLMDescriptionProvider(
        base_url=f"http://{args.vllm_host}:{args.vllm_port}",
        model=args.vllm_model, temperature=0.1, max_tokens=256, timeout=120.0)

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
            description_provider=desc_provider)
        t0 = time.monotonic()
        results = build(project_layout=project_layout, build_service=build_service,
                        datasource_ids=[ds_id], should_index=True,
                        should_enrich_context=True)
        logger.info("done in %.1f min: %s",
                     (time.monotonic() - t0) / 60,
                     [(str(r.datasource_id), str(r.status)) for r in results])


if __name__ == "__main__":
    main()
