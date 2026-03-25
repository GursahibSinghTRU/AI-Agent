# TRU Risk & Safety Assistant

A **local, 100% free** AI chatbot for Thompson Rivers University (TRU) Risk & Safety Services. Powered by **context injection** with local LLMs — no cloud APIs, no subscriptions, completely private.

The application features a full TRU-branded website with an embedded floating chat widget that answers policy questions with markdown hyperlinks to source documents. Responses stream token-by-token for a responsive user experience.

**Status:** ✅ Working | **Architecture:** Context Injection + Ollama (Qwen 3.5) | **Analytics:** Supabase PostgreSQL | **Framework:** FastAPI + React-inspired Vanilla JS

---

## What's New (vs Original RAG Approach)

✨ **New Context Injection Architecture:**
- ❌ No ChromaDB indexing overhead
- ❌ No chunking or embedding generation
- ✅ Single `combined_context.txt` file with all policies
- ✅ Direct context injection into LLM as first message
- ✅ Faster startup, simpler deployment
- ✅ Markdown hyperlinks with proper citation support

📱 **Multi-Page Frontend:**
- `GET /` → Risk & Safety Services (default homepage with chatbot)
- `GET /general` → General TRU landing/dummy page
- `GET /analytics` → Internal analytics dashboard
- Both pages include the embedded AI chatbot widget

📊 **Privacy-First Analytics (Supabase):**
- Session tracking, interaction telemetry, and user feedback
- No raw messages stored — only metadata and performance metrics
- Real-time analytics dashboard with KPIs, heatmaps, and charts
- Powered by Supabase PostgreSQL with Row Level Security

---

## Prerequisites

- **Python 3.10+**
- **Ollama** running locally — [ollama.com](https://ollama.com)
- **Ollama Models:**
  - `qwen3.5:0.8b` (Chat, ~1 GB)
  - Optional: `llama3:8b` or other models

---

## Quick Start

### 1. Setup Virtual Environment

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate     # Mac/Linux
```

### 2. Install Dependencies

```bash
pip install fastapi uvicorn httpx pydantic
```

### 3. Pull Ollama Models

```bash
ollama pull qwen3.5:0.8b
```

### 4. Prepare Your Data

Place all policy `.txt` files in the **`data/`** folder (or they already exist in the repo).

### 5. Build Combined Context

```bash
python build_context.py
```

This generates `data/combined_context.txt` by concatenating all `.txt` files with separators like `--- filename.txt`.

### 6. Start the Server

```bash
python run.py
```

Server starts on **http://localhost:8000**

Visit:
- `http://localhost:8000/` — Risk & Safety homepage with chatbot
- `http://localhost:8000/general` — General TRU page
- `http://localhost:8000/analytics` — Analytics dashboard

### 7. Quick Command

.\venv\Scripts\Activate.ps1; python run.py

---

## Project Structure

```
AI-Agent/
 app/
    agent.py          # Context injection agent (no RAG)
    config.py         # Settings & environment variables
    server.py         # FastAPI routes + SSE streaming
    supabase_client.py # Supabase CRUD helpers (sessions, interactions, feedback)
    __init__.py
 frontend/
    index.html        # Risk & Safety Services homepage
    general-tru.html  # General TRU landing page
    analytics.html    # Analytics dashboard (reads from Supabase)
    chatbot.js        # Floating chat widget (context-aware UI)
    chatbot.css       # TRU-branded widget styles + hyperlink styling
 data/
    *.txt             # Policy text files
    combined_context.txt  # Auto-generated concatenated context
 build_context.py     # Generate combined_context.txt
 clean_html.py        # Utility to clean corrupted characters from HTML
 run.py               # Uvicorn startup
 requirements.txt
 README.md
```

---

## Configuration

Edit **`app/config.py`** for custom settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `CHAT_MODEL` | `qwen3.5:0.8b` | Ollama chat model identifier |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `DATA_DIR` | `data/` | Directory containing `.txt` policy files |
| `TEMPERATURE` | `0.7` | LLM creativity (0=deterministic, 1=creative) |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins |
| `SUPABASE_URL` | *(project URL)* | Supabase project REST API URL |
| `SUPABASE_ANON_KEY` | *(project key)* | Supabase anonymous/public API key |

Override via environment variables:

```bash
CHAT_MODEL=llama3:8b TEMPERATURE=0.5 python run.py
```

---

## System Prompt

The AI's instructions are defined in **`app/agent.py`** (see `SYSTEM_PROMPT` variable).

**Key behaviors:**
1. Treats the combined context as ground truth
2. Only answers questions found in the provided context
3. Cites sources as markdown hyperlinks: `[Source Name](URL)`
4. Ends responses with helpful next-step questions
5. Professional, neutral tone reflecting TRU brand values

Edit `SYSTEM_PROMPT` in `agent.py` to customize tone or behavior.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves Risk & Safety homepage |
| `GET` | `/general` | Serves General TRU page |
| `GET` | `/analytics` | Serves analytics dashboard |
| `GET` | `/api/health` | Health check (Ollama status) |
| `GET` | `/api/stats` | Context file info |
| `POST` | `/api/chat/stream` | SSE streaming chat |
| `POST` | `/api/chat` | Non-streaming fallback |
| `POST` | `/api/session` | Create/touch a chat session |
| `POST` | `/api/feedback` | Submit thumbs up/down feedback |

### Streaming Chat Event Format

`POST /api/chat/stream` returns `text/event-stream` with these events:

```json
data: {"type":"sources","sources":[{"file":"combined_context.txt","policy":"All Documents","relevance":1.0}]}
data: {"type":"token","token":"Here"}
data: {"type":"token","token":" is"}
...
data: {"type":"done","timing":{"total_ms":2100,"llm_ms":2055,"retrieve_ms":0}}
```

---

## Console Debugging

Browser console logs all received tokens and rendered markdown for debugging:

```javascript
[TRU Chat] Received token: "..."
[TRU Chat] Full response so far: "..."
[TRU Chat] Rendered markdown HTML: "<p>...</p>"
```

Open DevTools (F12 → Console) while chatting to see real-time output.

---

## Embedding on WordPress

To embed the chatbot on an external WordPress site:

### 1. Deploy Backend to Production

Host `app/server.py` on a production server (AWS, Heroku, etc.) with a public URL like `https://your-api.com`

### 2. Update JavaScript Configuration

Modify `frontend/chatbot.js` to accept a configurable API URL:

```javascript
window.TRUChatbotConfig = {
  apiBaseUrl: 'https://your-api.com',
  apiStream: '/api/chat/stream'
};
```

### 3. Host Chatbot JS File

Push `frontend/chatbot.js` + `frontend/chatbot.css` to a CDN or GitHub:

```
https://cdn.jsdelivr.net/gh/YourOrg/AI-Agent@latest/frontend/chatbot.js
https://cdn.jsdelivr.net/gh/YourOrg/AI-Agent@latest/frontend/chatbot.css
```

### 4. Add to WordPress

In WordPress theme or via plugin:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/YourOrg/AI-Agent@latest/frontend/chatbot.css?v=1">
<script src="https://cdn.jsdelivr.net/gh/YourOrg/AI-Agent@latest/frontend/chatbot.js?v=1"></script>
```

Or create a WordPress plugin:

```php
<?php
/**
 * Plugin Name: TRU Chatbot
 */
add_action('wp_footer', function() {
    wp_enqueue_style('tru-chat', 'https://cdn.jsdelivr.net/gh/YourOrg/...chatbot.css?v=1');
    wp_enqueue_script('tru-chat', 'https://cdn.jsdelivr.net/gh/YourOrg/...chatbot.js?v=1', array(), '1.0', true);
});
```

---

## Features

✅ **100% Local** — No cloud dependencies for chat, all processing on-device  
✅ **Context-First** — All answers grounded in provided policy documents  
✅ **Markdown Hyperlinks** — Citations are clickable links to source files  
✅ **Streaming Responses** — Token-by-token generation for responsive UI  
✅ **TRU Branded** — Full design system following TRU brand guidelines  
✅ **Responsive** — Works on desktop, tablet, and mobile  
✅ **Multi-Page** — Risk & Safety + General TRU landing pages  
✅ **Embeddable** — Single JS file for easy WordPress integration  
✅ **Privacy-First Analytics** — Session & interaction telemetry via Supabase  
✅ **Analytics Dashboard** — KPI cards, heatmaps, charts, feedback breakdown  

---

## TRU Brand Guidelines

All design follows [TRU's official brand guide](tru-brand-guide_SKILL.md):

- **Colours:** Blue (#003e51), Teal (#00b0b9), Yellow (#ffcd00), Sage, Grey
- **Typography:** Roboto (body), Roboto Slab (headings)
- **Tone:** Purposeful, empowering, collaborative, open, visionary
- **Voice:** Confident but not arrogant; warm and inclusive

---

## Troubleshooting

**Chatbot widget not showing:**
- Ensure `/static/chatbot.css?v=1` loads (check DevTools Network tab)
- Verify `frontend/chatbot.js` is being served
- Clear browser cache or use private/incognito mode

**No response from chatbot:**
- Confirm Ollama is running: `ollama list`
- Check that `qwen3.5:0.8b` is installed: `ollama pull qwen3.5:0.8b`
- Verify `data/combined_context.txt` exists and is not empty
- Check browser console for JavaScript errors (F12 → Console)
- Check server logs for backend errors

**CSS not applying:**
- Add cache-busting query param: `/static/chatbot.css?v=2`
- Hard refresh browser (Ctrl+Shift+R)
- Verify CSS file size in DevTools Network tab

---

## Git Branch

All changes tracked in: `feature/context-injection-approach`

```bash
git checkout feature/context-injection-approach
git log --oneline
```

---

## License & Attribution

Thompson Rivers University (TRU) brand guidelines and materials are property of TRU.

This project is open-source for educational and non-commercial use.

---

## Contact & Support

- **TRU Risk & Safety Services:** safety@tru.ca
- **Questions:** Check the `/api/health` endpoint or review browser console logs
- **Issues:** Ensure Ollama is running and models are pulled

**Happy chatting! 🎓**
