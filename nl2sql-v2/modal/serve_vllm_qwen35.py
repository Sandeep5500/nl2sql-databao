"""Serve Qwen3.5-9B with vLLM on Modal -- same flags as slurm/serve_vllm_qwen35.slurm.

    modal secret create nl2sql-vllm VLLM_API_KEY=<random>     # once
    modal deploy nl2sql-v2/modal/serve_vllm_qwen35.py          # prints the URL
    # runner: --endpoint https://<workspace>--nl2sql-vllm-qwen35-serve.modal.run/v1
    #         with VLLM_API_KEY set in the environment
    modal app stop nl2sql-vllm-qwen35                          # when done

The container scales to zero after SCALEDOWN idle seconds; the first request after
that cold-starts (~3-6 min: weights come from the hf-cache volume after the first run).
"""

import os
import subprocess

import modal

MODEL = os.environ.get("MODEL", "Qwen/Qwen3.5-9B")
GPU = os.environ.get("GPU", "L40S")              # 48GB: 9B bf16 + 60k ctx KV fits
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "60000"))
PORT = 8000
SCALEDOWN = 20 * 60

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("vllm==0.18.1", "huggingface_hub[hf_transfer]")
    # vLLM 0.18.1 pins an older transformers that does not know qwen3_5; the serve
    # script overrides it the same way (see CLAUDE.md "Serving notes")
    .run_commands("pip install -U 'transformers==5.5.3' 'regex>=2025.10.22'")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_MLA_DISABLE": "1"})
)
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)

app = modal.App("nl2sql-vllm-qwen35")


@app.function(
    image=image,
    gpu=GPU,
    timeout=24 * 60 * 60,
    scaledown_window=SCALEDOWN,
    max_containers=1,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
    secrets=[modal.Secret.from_name("nl2sql-vllm")],
)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=PORT, startup_timeout=30 * 60)
def serve():
    cmd = [
        "vllm", "serve", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--served-model-name", MODEL,
        "--max-model-len", str(MAX_MODEL_LEN),
        "--gpu-memory-utilization", "0.92",
        "--dtype", "bfloat16",
        "--trust-remote-code",
        "--enable-auto-tool-choice",
        "--tool-call-parser", "qwen3_coder",
        "--reasoning-parser", "qwen3",
        "--api-key", os.environ["VLLM_API_KEY"],
    ]
    subprocess.Popen(cmd)
