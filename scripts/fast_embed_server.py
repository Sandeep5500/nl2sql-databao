#!/usr/bin/env python3
"""
Fast Ollama-compatible embedding server backed by HuggingFace sentence-transformers.

Replaces the slow Ollama nomic-embed-text with direct PyTorch/CUDA inference.
Implements only the /api/embed endpoint that DCE needs.

Usage:
    # Run before `dce build` / `dce index`, on same port as Ollama (or use --port)
    python fast_embed_server.py [--port 11434] [--model nomic-ai/nomic-embed-text-v1.5]

    # After DCE build is done, you can kill this and restart real Ollama for inference.
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

# ── Lazy-loaded model ────────────────────────────────────────────────────────
_model = None
_model_lock = threading.Lock()
_model_name = "nomic-ai/nomic-embed-text-v1.5"
_dim = 768


def load_model(model_name: str):
    global _model, _model_name
    print(f"Loading embedding model: {model_name}", flush=True)
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}", flush=True)
    m = SentenceTransformer(model_name, trust_remote_code=True, device=device)
    _model = m
    _model_name = model_name
    elapsed = time.time() - t0
    print(f"  Loaded in {elapsed:.1f}s", flush=True)
    # Warm up
    _ = m.encode(["warmup"], normalize_embeddings=True)
    print("  Warmed up, ready.", flush=True)


def embed(texts: list[str]) -> list[list[float]]:
    with _model_lock:
        vecs = _model.encode(texts, normalize_embeddings=True, batch_size=256, show_progress_bar=False)
        return vecs.tolist()


# ── HTTP server ──────────────────────────────────────────────────────────────

class OllamaCompatHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence request logs

    def do_GET(self):
        if self.path == "/":
            self._respond(200, b"Ollama is running")
        elif self.path == "/api/tags":
            # DCE checks for model availability via this endpoint
            body = json.dumps({
                "models": [
                    {"name": "nomic-embed-text:v1.5", "model": "nomic-embed-text:v1.5", "size": 274000000}
                ]
            }).encode()
            self._respond(200, body, content_type="application/json")
        else:
            self._respond(404, b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/api/embed":
            self._handle_embed(body)
        elif self.path == "/api/show":
            # DCE checks if model is available
            payload = json.loads(body)
            resp = json.dumps({"modelfile": "", "details": {"family": "bert"}}).encode()
            self._respond(200, resp, content_type="application/json")
        elif self.path == "/api/pull":
            # Pretend model is already pulled
            resp = json.dumps({"status": "success"}).encode()
            self._respond(200, resp, content_type="application/json")
        else:
            self._respond(404, b"Not found")

    def _handle_embed(self, body: bytes):
        try:
            payload = json.loads(body)
            input_data = payload.get("input", [])
            if isinstance(input_data, str):
                input_data = [input_data]
            if not input_data:
                self._respond(400, b"Missing 'input'")
                return

            t0 = time.time()
            vecs = embed(input_data)
            elapsed = time.time() - t0
            print(f"  /api/embed n={len(input_data)} → {elapsed*1000:.0f}ms", flush=True)

            resp = json.dumps({
                "model": "nomic-embed-text:v1.5",
                "embeddings": vecs,
            }).encode()
            self._respond(200, resp, content_type="application/json")
        except Exception as e:
            print(f"  /api/embed ERROR: {e}", flush=True)
            self._respond(500, str(e).encode())

    def _respond(self, code: int, body: bytes, content_type: str = "text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--model", type=str, default="nomic-ai/nomic-embed-text-v1.5")
    args = parser.parse_args()

    # Load model before starting server
    load_model(args.model)

    server = HTTPServer(("127.0.0.1", args.port), OllamaCompatHandler)
    print(f"\nFast embed server listening on 127.0.0.1:{args.port}", flush=True)
    print("Ready for DCE build/index commands.\n", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
