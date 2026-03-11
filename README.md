# TRU Policy Assistant

A **local, 100% free** RAG (Retrieval-Augmented Generation) chatbot for querying Thompson Rivers University policy documents. Every answer is grounded in official policy PDFs  no cloud APIs, no subscriptions, completely private.

The UI is a full TRU-branded website with a floating chat widget powered by the RAG backend. Answers stream token-by-token with Markdown formatting and document citations shown below each response.

**Status:  Working**  Qwen 3.5  nomic-embed-text  ChromaDB  FastAPI

---

## Architecture

```
PDF files  pypdf  text chunks  nomic-embed-text (Ollama)  ChromaDB
                                                                    
User asks a question in the chat widget
    embed question  cosine similarity search in ChromaDB
    top matching chunks  qwen3.5:0.8b (Ollama)  streaming answer
    rendered as Markdown with citation chips
```

---

## Prerequisites

- **Python 3.10+**
- **Ollama** installed and running  [ollama.com](https://ollama.com)

---

## Quick Start

### 1. Pull the models

```bash
ollama pull nomic-embed-text    # Embeddings (274 MB)
ollama pull qwen3.5:0.8b        # Chat LLM (1 GB)  fast and local
```

### 2. Install Python dependencies

```bash
pip install fastapi uvicorn pypdf chromadb httpx
```

### 3. Add your PDFs

Drop TRU policy PDF files into the **`data/`** folder.

### 4. Ingest documents

```bash
python ingest.py              # Incremental  add new PDFs only
python ingest.py --fresh      # Wipe vector DB and re-ingest everything
```

Use `--fresh` whenever you add or remove PDFs to keep the index clean.

### 5. Start the server

```bash
python run.py
```

Open **http://localhost:8000** in your browser — the TRU-branded page loads. Click the chat button (bottom-right FAB) to start asking policy questions.

---

## Project Structure

```
FunctionalRAGAgent/
 app/
    agent.py        # RAG pipeline: retrieve  generate
    config.py       # All tunables (models, thresholds, paths)
    rag_core.py     # ChromaDB setup, embedding helpers
    server.py       # FastAPI routes + SSE streaming
    __init__.py
 frontend/
    index.html      # Full TRU-branded university website
    chatbot.css     # TRU-branded widget styles + Markdown prose
    chatbot.js      # Floating chat widget  calls RAG API, streams
                         answers, renders Markdown + source citations
 data/               # Drop your policy PDFs here
 chroma_db/          # ChromaDB persistent vector store (auto-created)
 ingest.py           # PDF  chunk  embed  ChromaDB
 run.py              # Starts uvicorn on port 8000
 requirements.txt
 tru-brand-guide_SKILL.md   # TRU brand colours, fonts, tone reference
```

---

## Configuration

Edit `app/config.py` to change any of these:

| Setting | Default | Description |
|---|---|---|
| `CHAT_MODEL` | `qwen3.5:0.8b` | Ollama chat model |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API |
| `DATA_DIR` | `data/` | Folder to read PDFs from |
| `CHROMA_PATH` | `chroma_db/` | ChromaDB storage |
| `SIMILARITY_THRESHOLD` | (low) | Min cosine similarity to include a chunk |
| `TOP_K` | `5` | Number of chunks retrieved per query |

All settings can be overridden via environment variables of the same name (uppercased):

```bash
CHAT_MODEL=llama3:8b python run.py
```

### System Prompt

The system prompt (instructions for how the LLM should behave) is defined in **`app/rag_core.py`** starting at line 238. The `SYSTEM_PROMPT` constant tells the model to:
- Answer only from provided policy documents
- Return "Not found in the provided documents" if no answer is available
- Cite policy names and page numbers
- Use professional language and concise format

Edit `SYSTEM_PROMPT` in `app/rag_core.py` to customize the behaviour or tone of responses.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves the TRU-branded HTML frontend |
| `GET` | `/api/health` | Deep health check (Ollama + models) |
| `GET` | `/api/stats` | Document and chunk counts |
| `POST` | `/api/chat/stream` | SSE streaming RAG chat |
| `POST` | `/api/chat` | Non-streaming fallback |

### Chat stream event format

The `POST /api/chat/stream` endpoint returns `text/event-stream` with these event types:

```
data: {"type":"sources","sources":[{"policy":"...","page":1,"relevance":0.82}]}
data: {"type":"token","token":"Here"}
data: {"type":"token","token":" are"}
...
data: {"type":"done","timing":{"total_s":2.1,"retrieve_ms":45,"llm_ms":2055}}
```

---

## Frontend

The frontend is pure HTML/CSS/JS  no build tools, no framework.

### `frontend/index.html`
Full TRU university website layout (nav, hero, programs, campus life, admissions, footer) using TRU brand colours, Roboto + Roboto Slab fonts. The chatbot widget is injected by `chatbot.js` at page load.

### `frontend/chatbot.css`
TRU-branded floating widget styles:
- Floating Action Button (bottom-right)
- Chat window: header, messages area, input bar
- **Markdown prose styles** scoped to `.tru-message.assistant .tru-msg-bubble`  bold in TRU Blue, teal list markers, blockquotes, headings, code snippets
- Source citation chips: document name, page number, relevance %

### `frontend/chatbot.js`
Self-contained IIFE that:
1. Injects the chat FAB and window into the page DOM
2. Checks `/api/health` on load and shows connection status
3. On send  calls `/api/chat/stream` via SSE
4. Parses `sources`, `token`, and `done` events
5. Renders assistant text with **marked.js** (loaded from CDN via `index.html`)
6. Displays citation chips (document source, page, match %) below each answer
7. Shows quick-reply chips with common policy questions on first open

---

## Notes

- **Qwen 3.5 thinking mode**: The model internally reasons before answering. Thinking output is disabled via `"think": false` in the Ollama API call (see `app/agent.py`) for clean, direct responses.
- **Similarity threshold**: With a small corpus (< 50 chunks) the default threshold may filter everything out. Lower the `SIMILARITY_THRESHOLD` in `config.py` if you see "Not found in documents".
- **Fresh ingest**: Always run `python ingest.py --fresh` after adding or deleting PDFs to avoid stale vectors.
- **Docker**: A `Dockerfile` and `docker-compose.yml` are included but assume Ollama is accessible on the host network.

---

## Troubleshooting

### Can't reach http://0.0.0.0:8000

If you see **"Hmmm… can't reach this page"**, you're trying to visit the server's bind address directly. `0.0.0.0` is an internal bind address (listens on all interfaces) but isn't routable in browsers.

**Solution:** Use `http://localhost:8000` or `http://127.0.0.1:8000` instead. The server is running fine — you just need the correct URL in your browser.

The default HOST in `app/config.py` is now `localhost`, so this shouldn't happen. If you changed it back to `0.0.0.0`, revert it or always access via `http://localhost:8000`.

---

### Port 8000 Already in Use

If you get an error like `Address already in use` when running `python run.py`, the port is occupied. You have two options:

#### Option 1: Kill the existing process on port 8000

**Windows PowerShell:**
```powershell
# Find and kill the process using port 8000
Get-Process python | Where-Object { $_.CommandLine -like "*run.py*" } | Stop-Process -Force
```

**Linux/macOS:**
```bash
# Find the process on port 8000
lsof -i :8000
# Kill by PID
kill -9 <PID>
```

#### Option 2: Run on a different port

Edit `run.py` and change the port number:

```python
# Current (port 8000)
uvicorn.run(app, host="0.0.0.0", port=8000)

# Change to (port 8001)
uvicorn.run(app, host="0.0.0.0", port=8001)
```

Or use an environment variable without editing:

```bash
PORT=8001 python run.py
```

Then open **http://localhost:8001** in your browser.

#### Option 3: Check what's using the port

**Windows PowerShell:**
```powershell
netstat -ano | findstr :8000
# Shows: TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    12345
# Then kill by PID: Stop-Process -Id 12345 -Force
```

**Linux/macOS:**
```bash
lsof -i :8000
# Shows all processes using port 8000
```
