#!/bin/bash
# Start Ollama server for DCE embeddings (CPU/GPU, default port 11434).
# Run this on the login node before dce build / dce index.

OLLAMA_BIN="/data/user_data/sandeep3/personal/capstone/bin/bin/ollama"
OLLAMA_LIB="/data/user_data/sandeep3/personal/capstone/bin/lib/ollama"
OLLAMA_MODELS="/data/user_data/sandeep3/.cache/ollama"

# Kill any existing Ollama
pkill -f "ollama serve" 2>/dev/null || true
sleep 1

export OLLAMA_MODELS="$OLLAMA_MODELS"
export OLLAMA_HOST="127.0.0.1:11434"
export LD_LIBRARY_PATH="$OLLAMA_LIB:${LD_LIBRARY_PATH}"

echo "Starting Ollama on $OLLAMA_HOST (with CUDA libs from $OLLAMA_LIB)..."
"$OLLAMA_BIN" serve >> /tmp/ollama.log 2>&1 &
OLLAMA_PID=$!
echo "PID: $OLLAMA_PID"

sleep 4
if curl -s http://127.0.0.1:11434/ | grep -q "Ollama"; then
    echo "Ollama is running (PID $OLLAMA_PID)"
    echo "Models: $("$OLLAMA_BIN" list 2>/dev/null)"
else
    echo "ERROR: Ollama failed to start. Check /tmp/ollama.log"
    exit 1
fi
