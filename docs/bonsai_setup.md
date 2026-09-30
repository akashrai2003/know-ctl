# Running Social Graph with Bonsai 2 (27B Local AI on 8GB VRAM Laptops)

This guide walks you through running **Bonsai 2 (27B)** locally alongside **Social Graph**. Thanks to ternary-weight quantization, you can now run a full **27-billion parameter reasoning model completely local on consumer hardware with only 8GB VRAM** (such as RTX 3070/4060 laptop GPUs, desktop cards, or Apple Silicon Macs).

---

## ⚡ Why Bonsai 2 is a Game-Changer for Social Graph

Previously, running local LLMs for Social Graph's classification, summarization, and briefing pipelines required either:
- Expensive cloud API tokens (Groq/OpenAI/Anthropic), or
- Heavy 16GB–24GB+ VRAM workstations for 14B–32B models, or
- Smaller 7B–9B models that struggle with complex classification and deep multi-source synthesis.

### Hardware & Intelligence Breakdown

| Metric | Traditional FP16 27B | Bonsai 2 27B (`PTQ1_0`) |
|:---|:---|:---|
| **Weight Precision** | 16-bit float | **1.75 bits per weight** (Ternary) |
| **Model Disk/VRAM Footprint** | ~54 GB | **~5.6 GB** |
| **Minimum Hardware Required** | 2x RTX 3090 / 4090 | **Single 8GB VRAM Laptop GPU** |
| **Intelligence Retention** | 100% baseline | **98.2% of FP16 intelligence retained** |
| **Context Window on 8GB VRAM** | Impossible | **24,576 tokens** (with Q8 KV cache + FlashAttention) |

With **Bonsai 2 27B**, Social Graph can execute high-volume article enrichment, comment filtering, post categorization, and even complete multi-source AI briefing synthesis with zero cloud API dependencies.

---

## 🛠️ Step 1: Clone and Set Up Bonsai-demo

PrismML provides the [Bonsai-demo](https://github.com/PrismML-Eng/Bonsai-demo) repository, which includes optimized `llama.cpp` binaries pre-compiled with ternary kernels and Hadamard transform support.

```bash
# 1. Clone the Bonsai-demo repository
cd ~/Desktop
git clone https://github.com/PrismML-Eng/Bonsai-demo.git
cd Bonsai-demo

# 2. Run the automated setup script
./setup.sh
```

### What `setup.sh` does automatically:
1. Detects your hardware (NVIDIA CUDA, Apple Silicon Metal, Vulkan, or CPU).
2. Sets up a local Python environment using `uv`.
3. Downloads the hardware-optimized binaries into `bin/` (e.g. `bin/cuda/llama-server`).
4. Downloads the default Bonsai-2-27B GGUF weights into `models/bonsai2-gguf/27B/`.

> [!TIP]
> If you need to manually download or ensure you have the ultra-compact **5.6 GB `PTQ1_0` packing** (ideal for 8GB VRAM), you can fetch it with Python:
> ```bash
> python3 -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='prism-ml/Ternary-Bonsai-2-27B-gguf', local_dir='models/bonsai2-gguf/27B', allow_patterns=['*PTQ1_0.gguf'])"
> ```

---

## 🚀 Step 2: Launch the Bonsai 2 Server (Optimized for 8GB VRAM)

Run the CUDA-optimized `llama-server` with FlashAttention and 8-bit quantized KV caching. This configuration fits comfortably inside 8GB VRAM while offering a massive 24,576 token context window:

```bash
cd ~/Desktop/Bonsai-demo

./bin/cuda/llama-server \
  -m models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf \
  -ngl 99 \
  -c 24576 \
  -fa on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --jinja \
  --reasoning-effort medium \
  --reasoning-format auto \
  --host 0.0.0.0 \
  --port 8080
```

### Flag Explanation for 8GB VRAM Tuning:

- `-m models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf`: The 1.75-bit ternary weights (~5.6 GB).
- `-ngl 99`: Offloads all 99 model layers entirely into GPU memory.
- `-c 24576`: 24k token context window, allowing processing of long articles and discussion threads.
- `-fa on`: Enables FlashAttention to slash memory consumption and accelerate prefill.
- `--cache-type-k q8_0 --cache-type-v q8_0`: Quantizes keys and values in KV cache from FP16 down to 8-bit, saving ~50% VRAM with negligible loss in precision.
- `--jinja`: Enables Jinja chat templating required for native OpenAI tool calling and structured completions.
- `--reasoning-effort medium --reasoning-format auto`: Enables reasoning traces and thinking tokens.
- `--host 0.0.0.0 --port 8080`: Binds the OpenAI-compatible HTTP server to port 8080.

### 8GB VRAM Memory Budget:
```text
┌────────────────────────────────────────────────────────┐
│ Total VRAM Available: 8,192 MB                         │
├───────────────────────────────┬────────────────────────┤
│ Component                     │ Memory Allocated       │
├───────────────────────────────┼────────────────────────┤
│ Model Weights (PTQ1_0)        │ ~5,600 MB              │
│ KV Cache (24k tokens @ Q8_0)  │ ~1,200 MB              │
│ CUDA Context & Scratch Buffer │ ~700 MB                │
├───────────────────────────────┼────────────────────────┤
│ Total Allocated               │ ~7,500 MB (SAFE HEADROOM)
└───────────────────────────────┴────────────────────────┘
```

---

## ⚠️ Step 3: Port Coordination (`8080` vs `3000`)

Both `llama-server` and Social Graph Web UI (`sg web`) default to port `8080`. To avoid port conflicts:

1. **Keep Bonsai `llama-server` on port `8080`** (`http://127.0.0.1:8080`).
2. **Run Social Graph Web UI on port `3000`**:
   ```bash
   sg web --port 3000
   ```
   Or set `SG_WEB_PORT=3000` in your `.env`.

---

## ⚙️ Step 4: Configure Social Graph to Use Bonsai

You can configure Social Graph through either the Web UI or a `.env` file.

### Option A: Via the Web UI Dashboard

1. Launch the Social Graph Web UI:
   ```bash
   sg web --port 3000
   ```
2. Navigate to `http://localhost:3000/#/settings`.
3. In the **Local Model Server** section, fill in:
   - **Base URL**: `http://127.0.0.1:8080`
   - **Model ID**: `models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf`
4. Click **Save Settings** (credentials are securely stored in your local SQLite store).

### Option B: Via `.env` File

Add or update the following variables in your `.env` file:

```env
# Local Model Server (Bonsai 2 27B via llama-server)
SG_VLLM_BASE_URL=http://127.0.0.1:8080
SG_VLLM_MODEL=models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf

# Social Graph Web UI port (avoids conflict with llama-server on 8080)
SG_WEB_PORT=3000

# Concurrency & Timeout
SG_BATCH_SIZE=8
SG_LLM_TIMEOUT=580.0
```

---

## 🧪 Step 5: Test Server Connectivity

Verify your Bonsai server is responding correctly using `curl`:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf",
    "messages": [
      {"role": "user", "content": "Explain what a knowledge graph is in one sentence."}
    ],
    "temperature": 0.7
  }'
```

You should see an OpenAI-compatible JSON response with reasoning tokens and output.

---

## 🏃 Step 6: Running Social Graph Pipelines with Bonsai

Once configured, Social Graph's `HybridLLMClient` will automatically detect the OpenAI-compatible `/v1/chat/completions` endpoint and route requests concurrently.

### Run High-Throughput Classification Locally:
Categorize all your saved posts using Bonsai 2 27B:
```bash
sg classify --force
```

### Run Subtopic Detection & Hierarchical Organization:
Generate titles and discover granular subtopics across categories:
```bash
sg subtopic --force
```

### Generate 100% Local AI Briefings:
Generate comprehensive evidence-backed briefings without touching cloud APIs:
```bash
sg insights --provider local
```

### Run Full End-to-End Pipeline:
```bash
sg run
```

---

## 💡 Troubleshooting & Tips for 8GB VRAM Machines

### 1. CUDA Out of Memory (OOM) during extreme load
If you encounter memory spikes with multiple concurrent requests:
- Switch KV cache to 4-bit (`--cache-type-k q4_0 --cache-type-v q4_0`), which saves an additional ~600 MB of VRAM.
- Reduce context window slightly from 24,576 to 16,384 (`-c 16384`).
- Lower `SG_BATCH_SIZE` in `.env` to `4` or `6`.

### 2. Apple Silicon Macs (Metal)
On Apple Silicon MacBooks (M1/M2/M3/M4 with unified memory), Bonsai runs natively:
```bash
./bin/mac/llama-server \
  -m models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PTQ1_0.gguf \
  -ngl 99 -c 24576 -fa on \
  --host 0.0.0.0 --port 8080
```
Unified memory handles both weights and KV cache effortlessly.

### 3. Server Already Running Error
If port 8080 is already held:
```bash
kill $(lsof -ti TCP:8080)
```
