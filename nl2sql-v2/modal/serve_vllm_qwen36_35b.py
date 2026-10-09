"""Serve the Qwen3.6-35B-A3B (AWQ) actor on Modal -- the model the 35B results used.

    modal secret create nl2sql-vllm VLLM_API_KEY=<random>        # once
    modal deploy nl2sql-v2/modal/serve_vllm_qwen36_35b.py        # prints the URL
    modal app stop nl2sql-vllm-qwen36-35b                        # when done

Deliberately a separate file from serve_vllm_qwen35.py rather than a parameterisation
of it. That one reads MODEL from os.environ at module scope, but Modal re-imports the
module INSIDE the container, where the variable is not set -- so `MODEL=... modal
deploy` silently serves the 9B default. Constants here are literals for that reason.

MODEL must be the exact repo the published 35B numbers came from. It is recorded
nowhere in git (the tracked serve scripts only cover Qwen3.5-9B, the published traces
carry no model field, and traces_to_inspect.py --model defaults to the 9B whatever
actually ran), so confirm it against the serve command from that run before trusting a
comparison: a different AWQ quant of the same base is a different model.
"""

import os
import subprocess

import modal

# The official bf16 release (Qwen publishes no AWQ for this model, only FP8 and
# NVFP4; the attack plan's "AWQ" would have been a community quant). Using the
# official weights removes any question about which quantisation produced a
# number. ~72GB, arch Qwen3_5MoeForConditionalGeneration, 35B total / 3B active.
MODEL = "Qwen/Qwen3.6-35B-A3B"
SERVED_NAME = MODEL

# bf16 weights are ~72GB, so this needs a big-memory GPU: an L40S (48GB) or even
# an H100 (80GB) cannot hold the weights plus a 60K-token KV cache. H200 (141GB)
# fits comfortably on one device and avoids tensor-parallel overhead; the
# alternative is GPU="H100:2" with --tensor-parallel-size 2.
GPU = "H200"
MAX_MODEL_LEN = 60_000
PORT = 8000
SCALEDOWN = 20 * 60

# A CUDA *devel* base, not debian_slim: this model is the Qwen3-Next hybrid
# architecture, whose gated-delta-rule attention goes through FlashInfer, and
# FlashInfer JIT-COMPILES its kernel on the first inference. That needs nvcc.
# With a runtime-only image the model loads and /v1/models answers 200, then the
# first completion dies with "Could not find nvcc" and takes the server with it --
# which looks like a flaky endpoint, not a missing build dependency.
image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu24.04",
                              add_python="3.12")
    .apt_install("git")
    .uv_pip_install("vllm==0.18.1", "huggingface_hub[hf_transfer]")
    # vLLM 0.18.1 pins a transformers that does not know the qwen3_5+ architectures;
    # the regex floor goes with it (a plain reinstall silently downgrades regex).
    .run_commands("pip install -U 'transformers==5.5.3' 'regex>=2025.10.22'")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_MLA_DISABLE": "1",
          # FlashInfer looks here for nvcc; the devel image puts it at /usr/local/cuda
          "CUDA_HOME": "/usr/local/cuda",
          "PATH": "/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin",
          # keep JIT output on the cache volume so only the first start pays for it
          "FLASHINFER_WORKSPACE_BASE": "/root/.cache/vllm/flashinfer"})
)

# weights land here on the first start and are reused by every later container
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)

app = modal.App("nl2sql-vllm-qwen36-35b")


@app.function(
    image=image,
    gpu=GPU,
    timeout=24 * 60 * 60,
    scaledown_window=SCALEDOWN,
    # one replica is enough for a sharded run: A3B activates ~3B params per token,
    # so a single L40S serves many concurrent episodes. Raise if the shards saturate it.
    max_containers=1,
    # one mount per volume: Modal rejects the same Volume at two paths, and the
    # JIT cache lives inside the vllm cache rather than needing its own volume
    volumes={"/root/.cache/huggingface": hf_cache,
             "/root/.cache/vllm": vllm_cache},
    secrets=[modal.Secret.from_name("nl2sql-vllm")],
)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=PORT, startup_timeout=45 * 60)
def serve():
    cmd = [
        "vllm", "serve", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--served-model-name", SERVED_NAME,
        "--max-model-len", str(MAX_MODEL_LEN),
        "--gpu-memory-utilization", "0.92",
        "--trust-remote-code",
        # the checkpoint config declares quant_method=awq, so vLLM picks the
        # kernel itself (marlin where supported); forcing awq_marlin would fail
        # on a build where it is unavailable rather than falling back.
        "--enable-auto-tool-choice",
        "--tool-call-parser", "qwen3_coder",
        "--reasoning-parser", "qwen3",
        "--api-key", os.environ["VLLM_API_KEY"],
        # NOTE: no --enforce-eager. That was an A6000 bus-error workaround on Babel
        # and costs throughput; L40S/H100 do not need it.
    ]
    print("launching: " + " ".join(cmd), flush=True)
    subprocess.Popen(cmd)
