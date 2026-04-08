#!/usr/bin/env python3
"""DCE LLM Enrichment Script — calls vLLM instead of Ollama for description generation.

Implements a custom VLLMDescriptionProvider that speaks the OpenAI chat-completion
API directly, bypassing the Ollama layer entirely.  All other DCE internals
(embedding, chunking, indexing) are used unchanged.

Usage (standalone, server already running):
    cd /data/user_data/sandeep3/personal/capstone/databao-context-engine
    uv run python ../scripts/enrich_dce.py \\
        --vllm-host babel-u9-20 --vllm-port 8766 \\
        --vllm-model Qwen/Qwen3-32B-AWQ \\
        --dce-dir ../spider2-dce

Invoked automatically by serve_enrich_vllm.slurm.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich_dce")

# ── vLLM Description Provider ─────────────────────────────────────────────────


class VLLMDescriptionProvider:
    """Implements the DCE DescriptionProvider protocol against a vLLM OpenAI endpoint.

    Unlike OllamaDescriptionProvider this calls /v1/chat/completions (no streaming)
    and works with any model served by vLLM.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 256,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()

    # ── DescriptionProvider protocol ──────────────────────────────────────────

    @property
    def describer(self) -> str:
        return "vllm"

    @property
    def model_id(self) -> str:
        return self._model

    def describe(self, text: str, context: str) -> str:
        prompt = self.default_description_prompt(text=text, context=context)
        return self.prompt_for_description(prompt)

    def prompt_for_description(self, prompt: str) -> str:
        return self._call_with_retry(prompt)

    # ── Static helper (matches DCE's DescriptionProvider.default_description_prompt) ──

    @staticmethod
    def default_description_prompt(text: str, context: str) -> str:
        import textwrap

        base = """
            You are a helpful assistant.

            I will give you some TEXT and CONTEXT.
            Write a concise, human-readable description of the TEXT suitable for displaying in a UI.
            - 1-2 sentences
            - Be factual and avoid speculation
            - No markdown
            - No preambles or labels, just the description itself.
            - Your entire reply MUST be only the description itself. No extra commentary.

            CONTEXT:
            {context}

            TEXT:
            {text}
            """
        return textwrap.dedent(base).format(context=context, text=text).strip()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call_with_retry(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return self._call_once(prompt)
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("vLLM call failed (attempt %d/%d): %s — retrying in %ds", attempt, self._max_retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"vLLM call failed after {self._max_retries} attempts") from last_exc

    def _call_once(self, prompt: str) -> str:
        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resp = self._session.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip()

    def is_healthy(self, timeout: float = 5.0) -> bool:
        try:
            r = self._session.get(f"{self._base_url}/v1/models", timeout=timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def is_inference_ready(self, timeout: float = 10.0) -> bool:
        """Check that the model can actually serve inference (not just respond to /v1/models)."""
        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            r = self._session.post(url, json=payload, timeout=timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def wait_until_healthy(self, timeout: float = 1200.0, poll_interval: float = 5.0) -> bool:
        """Wait until the server passes the /v1/models check AND a test inference succeeds."""
        deadline = time.monotonic() + timeout
        # Phase 1: wait for /v1/models to respond
        while time.monotonic() < deadline:
            if self.is_healthy():
                break
            time.sleep(poll_interval)
        else:
            return False
        # Phase 2: wait for actual inference to be ready (model fully loaded)
        logger.info("Health check passed — waiting for inference readiness...")
        while time.monotonic() < deadline:
            if self.is_inference_ready():
                logger.info("Inference ready.")
                return True
            time.sleep(poll_interval)
        return self.is_inference_ready()


# ── Main enrichment logic ─────────────────────────────────────────────────────


def run_enrichment(
    *,
    dce_dir: Path,
    vllm_base_url: str,
    vllm_model: str,
    embed_host: str,
    embed_port: int,
) -> None:
    # Import DCE internals — must run inside the databao-context-engine venv
    from databao_context_engine.build_sources.build_runner import build
    from databao_context_engine.build_sources.build_service import BuildService
    from databao_context_engine.build_sources.types import DatasourceStatus
    from databao_context_engine.llm.config import OllamaConfig
    from databao_context_engine.llm.embeddings.ollama import OllamaEmbeddingProvider
    from databao_context_engine.llm.service import OllamaService
    from databao_context_engine.plugins.plugin_loader import DatabaoContextPluginLoader
    from databao_context_engine.project.layout import ensure_project_dir
    from databao_context_engine.services.factories import create_chunk_embedding_service
    from databao_context_engine.storage.connection import open_duckdb_connection
    from databao_context_engine.storage.migrate import migrate

    logger.info("Initialising DCE project at %s", dce_dir)
    project_layout = ensure_project_dir(project_dir=dce_dir)
    plugin_loader = DatabaoContextPluginLoader()

    # ── Embedding provider (fast_embed_server on embed_host:embed_port) ───────
    embed_config = OllamaConfig(host=embed_host, port=embed_port, bin_path="ollama", timeout=120.0)
    embed_service = OllamaService(config=embed_config)

    model_details = project_layout.project_config.ollama_embedding_model_details
    logger.info("Embedding model: %s (dim=%d)", model_details.model_id, model_details.model_dim)
    embedding_provider = OllamaEmbeddingProvider(service=embed_service, model_details=model_details)

    # ── vLLM description provider ─────────────────────────────────────────────
    desc_provider = VLLMDescriptionProvider(
        base_url=vllm_base_url,
        model=vllm_model,
        temperature=0.1,
        max_tokens=256,
        timeout=120.0,
    )
    logger.info("vLLM description provider ready: %s @ %s", vllm_model, vllm_base_url)

    # ── Full build + enrich + index pipeline ──────────────────────────────────
    # Using build() rather than run_enrich_context() so we start from the SQLite
    # source configs in src/databases/ and don't require pre-existing output YAMLs.
    # For databases whose output YAML is missing/deleted, this rebuilds from scratch.
    # For databases already correctly indexed, the hash check skips re-indexing.
    db_path = project_layout.db_path
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        migrate(db_path)

    with open_duckdb_connection(db_path) as conn:
        chunk_embedding_service = create_chunk_embedding_service(conn, embedding_provider=embedding_provider)

        build_service = BuildService(
            project_layout=project_layout,
            chunk_embedding_service=chunk_embedding_service,
            plugin_loader=plugin_loader,
            description_provider=desc_provider,
        )

        logger.info("Starting full build+enrich+index for all src databases...")
        t0 = time.monotonic()

        results = build(
            project_layout=project_layout,
            build_service=build_service,
            datasource_ids=None,       # auto-discover all from src/databases/
            should_index=True,
            should_enrich_context=True,
        )

        elapsed = time.monotonic() - t0

    ok = sum(1 for r in results if r.status == DatasourceStatus.OK)
    failed = sum(1 for r in results if r.status == DatasourceStatus.FAILED)
    skipped = sum(1 for r in results if r.status == DatasourceStatus.SKIPPED)

    logger.info(
        "Build+enrich complete in %.1f min — OK: %d  Failed: %d  Skipped: %d",
        elapsed / 60,
        ok,
        failed,
        skipped,
    )

    if failed:
        for r in results:
            if r.status == DatasourceStatus.FAILED:
                logger.error("  FAILED: %s — %s", r.datasource_id, getattr(r, "error", "?"))
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich DCE contexts with vLLM descriptions")
    parser.add_argument("--vllm-host", default="localhost", help="vLLM server hostname")
    parser.add_argument("--vllm-port", type=int, default=8766, help="vLLM server port")
    parser.add_argument("--vllm-model", default="Qwen/Qwen3-32B-AWQ", help="Model ID served by vLLM")
    parser.add_argument("--embed-host", default="localhost", help="fast_embed_server hostname")
    parser.add_argument("--embed-port", type=int, default=11434, help="fast_embed_server port")
    parser.add_argument(
        "--dce-dir",
        type=Path,
        default=Path("/data/user_data/sandeep3/personal/capstone/spider2-dce"),
        help="Path to the DCE project directory (contains dce.ini)",
    )
    parser.add_argument(
        "--wait-for-vllm",
        action="store_true",
        default=True,
        help="Wait for vLLM server to become healthy before starting (default: True)",
    )
    args = parser.parse_args()

    vllm_base_url = f"http://{args.vllm_host}:{args.vllm_port}"
    logger.info("vLLM endpoint: %s  model: %s", vllm_base_url, args.vllm_model)
    logger.info("Embed server:  http://%s:%d", args.embed_host, args.embed_port)
    logger.info("DCE project:   %s", args.dce_dir.resolve())

    if args.wait_for_vllm:
        logger.info("Waiting for vLLM server to be ready (up to 20 min)...")
        probe = VLLMDescriptionProvider(base_url=vllm_base_url, model=args.vllm_model)
        if not probe.wait_until_healthy(timeout=1200.0):
            logger.error("vLLM server at %s never became healthy", vllm_base_url)
            sys.exit(1)
        logger.info("vLLM server is ready.")

    run_enrichment(
        dce_dir=args.dce_dir,
        vllm_base_url=vllm_base_url,
        vllm_model=args.vllm_model,
        embed_host=args.embed_host,
        embed_port=args.embed_port,
    )


if __name__ == "__main__":
    main()
