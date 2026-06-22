# Quick Start

This guide covers model hosting, environment configuration, and running GeepSeek locally.

## 1. Model hosting (optional: Kaggle GPU)

If you do not already have an OpenAI-compatible endpoint, you can run Ollama on a GPU environment such as Kaggle.

### Install dependencies

```bash
apt-get update && apt-get install -y zstd
```

### Install Ollama

```bash
curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst -o ollama.tar.zst
tar -xvf ollama.tar.zst -C /usr
ollama --version
```

### Start the Ollama server

Run Ollama as a background process and bind it to all interfaces:

```python
import subprocess
import os
import time

env = os.environ.copy()
env["OLLAMA_MODELS"] = "/kaggle/working/ollama_models"
env["OLLAMA_HOST"] = "0.0.0.0"

log = open("ollama.log", "w")
process = subprocess.Popen(
    ["/usr/bin/ollama", "serve"],
    env=env,
    stdout=log,
    stderr=log,
)

time.sleep(5)
print(f"Ollama started — PID: {process.pid}")
```

### Pull a model

```bash
OLLAMA_HOST=0.0.0.0 ollama pull qwen3:8b
```

### Expose the endpoint (optional)

Use a tunnel service if the inference host is not reachable from your machine:

```bash
npm install -g localtunnel
lt --port 11434
```

Set the tunnel URL as `BASE_URL` in your `.env` file.

---

## 2. Application setup

From the repository root:

### Install Python packages

```bash
pip install -r requirements.txt
```

### Configure environment variables

Copy the example file and edit values for your provider:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `BASE_URL` | Base URL of your OpenAI-compatible API (no `/v1` suffix) |
| `API_KEY` | API key or placeholder (e.g. `ollama`) |
| `RESONNING_MODEL` | Model used when GeepThink is enabled |
| `NON_RESONNING_MODEL` | Default model when GeepThink is disabled |

### Start the services

Terminal 1 — API server:

```bash
python app/server/server.py
```

Terminal 2 — web client:

```bash
python app/client/serv.py
```

Use `python3` instead of `python` if required on your system.

---

## 3. Verify the installation

Open [http://127.0.0.1:5001/chat/new](http://127.0.0.1:5001/chat/new), send a message, and confirm that the response streams correctly.

If Search mode is enabled, verify that source links appear in the assistant reply.
