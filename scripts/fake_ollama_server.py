#!/usr/bin/env python3
"""
Fake Ollama server for PSC Bridges-2.

Mimics the Ollama HTTP API so that databao-context-engine (DCE) can build
dce.duckdb without needing a real Ollama installation.

Endpoints implemented:
  GET  /api/tags        — returns a fake model list (health check + model check)
  POST /api/pull        — no-op (model already "available")
  POST /api/embed       — sentence-transformers (nomic-embed-text-v1.5, 768-dim)
  POST /api/generate    — proxies to vLLM OpenAI-compatible endpoint

Usage:
  python scripts/fake_ollama_server.py --vllm-endpoint http://HOST:PORT --port 11434

The script downloads nomic-embed-text-v1.5 from HuggingFace on first run (~274 MB).
Subsequent runs load from HF cache.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [fake-ollama] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Globals set at startup ────────────────────────────────────────────────────
_embed_model = None   # sentence_transformers.SentenceTransformer
_vllm_base: str = ""  # e.g. "http://hostname:8765"
_vllm_model: str = "" # e.g. "XGenerationLab/XiYanSQL-QwenCoder-32B-2504"

FAKE_MODELS = ["nomic-embed-text:v1.5", "llama3.2:3b"]


def _load_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    # BAAI/bge-base-en-v1.5: 768-dim, no trust_remote_code needed, ~438MB.
    # Matches DCE's expected model_dim=768. Avoids the nomic model's
    # dynamic-module/einops check that fails spuriously in some venv setups.
    log.info("Loading BAAI/bge-base-en-v1.5 via sentence-transformers...")
    from sentence_transformers import SentenceTransformer
    _embed_model = SentenceTransformer("BAAI/bge-base-en-v1.5")
    log.info("Embedding model loaded (dim=768)")
    return _embed_model


def _embed(texts: list[str]) -> list[list[float]]:
    model = _load_embed_model()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def _generate(prompt: str, temperature: float = 0.1) -> str:
    if not _vllm_base:
        return ""
    url = f"{_vllm_base}/v1/completions"
    payload = {
        "model": _vllm_model,
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": temperature,
    }
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["text"].strip()
    except Exception as e:
        log.warning("vLLM generate failed: %s", e)
        return ""


class OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send_json({
                "models": [{"name": m, "model": m} for m in FAKE_MODELS]
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/pull":
            self._send_json({"status": "success"})

        elif self.path == "/api/embed":
            body = self._read_json()
            inp = body.get("input", "")
            texts = inp if isinstance(inp, list) else [inp]
            try:
                embeddings = _embed(texts)
                self._send_json({"embeddings": embeddings})
            except Exception as e:
                log.error("Embed error: %s", e)
                self._send_json({"error": str(e)}, 500)

        elif self.path == "/api/generate":
            body = self._read_json()
            prompt = body.get("prompt", "")
            temperature = body.get("options", {}).get("temperature", 0.1)
            try:
                response = _generate(prompt, temperature)
                self._send_json({"response": response, "done": True})
            except Exception as e:
                log.error("Generate error: %s", e)
                self._send_json({"error": str(e)}, 500)

        else:
            self._send_json({"error": "not found"}, 404)


def main():
    parser = argparse.ArgumentParser(description="Fake Ollama server for DCE on PSC")
    parser.add_argument("--port", type=int, default=11434, help="Port to listen on (default: 11434)")
    parser.add_argument("--vllm-endpoint", default="", help="vLLM base URL for generate calls, e.g. http://HOST:8765")
    parser.add_argument("--vllm-model", default="XGenerationLab/XiYanSQL-QwenCoder-32B-2504",
                        help="Model name to pass to vLLM for generate calls")
    args = parser.parse_args()

    global _vllm_base, _vllm_model
    _vllm_base = args.vllm_endpoint.rstrip("/")
    _vllm_model = args.vllm_model

    # Pre-load embedding model so first request is fast
    _load_embed_model()

    server = HTTPServer(("0.0.0.0", args.port), OllamaHandler)
    log.info("Fake Ollama server listening on port %d", args.port)
    log.info("  /api/embed   → nomic-embed-text-v1.5 (sentence-transformers, CPU)")
    log.info("  /api/generate → %s %s", _vllm_base or "(disabled)", _vllm_model)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
