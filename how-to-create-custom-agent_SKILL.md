# How to Create a Custom TRU RAG Agent

This guide documents every file you need to touch when building a new RAG-powered chatbot for a different domain (e.g. Student Wellness, Course Advisor, IT Help Desk, Indigenous Student Services, etc.). The base project is a FastAPI + ChromaDB + Ollama stack; each "agent" is the same codebase pointed at a different document collection with a different persona.

---

## Architecture Overview

```
app/
  config.py     ← Collection name, data folder, model settings
  rag_core.py   ← System prompt (persona + rules)
  server.py     ← FastAPI title (metadata only)
  agent.py      ← Pipeline (no change needed)
frontend/
  chatbot.js    ← Widget title, quick replies, welcome text
  index.html    ← Host page content, hero, sidebar, cards
data/           ← Drop domain-specific PDFs here
ingest.py       ← Re-run with --fresh when data changes
```

Each new agent needs its own **ChromaDB collection** and a separate data folder (or sub-folder). Everything else is configured via text edits.

---

## 1 — `app/config.py`  ← Start Here

This is the single source of truth for infrastructure settings.

| Setting | What to Change | Example |
|---|---|---|
| `COLLECTION_NAME` | **Unique per agent** — keeps vector stores separate | `"wellness_docs"` |
| `DATA_DIR` | Folder where ingestion reads PDFs from | `"data/wellness"` |
| `CHAT_MODEL` | Ollama model name | `"qwen3:0.6b"` / `"llama3.2:3b"` |
| `K` | Number of retrieved chunks (default 6) | Increase for dense Risk & Safety docs |
| `SCORE_THRESHOLD` | Similarity cutoff (default 1.0 = loose) | Lower = more selective |
| `TEMPERATURE` | LLM creativity (default 0.1 = factual) | Keep low for Risk & Safety/advisory |

**Example — Wellness Agent config:**
```python
COLLECTION_NAME: str = "wellness_docs"
DATA_DIR: str = "data/wellness"
```

All settings can also be overridden with environment variables (the field names match env var names), so you can run two agents on different ports without touching code — just set `COLLECTION_NAME=wellness_docs` in the environment.

---

## 2 — `app/rag_core.py` — Persona & Rules (Line ~238)

The `SYSTEM_PROMPT` constant defines who the agent *is*, what it knows, and what it will/won't do.

### Current (Risk & Safety Assistant):
```python
SYSTEM_PROMPT = (
    "You are the TRU Risk & Safety Assistant — an expert on Thompson Rivers University policies. "
    "Answer questions using ONLY the provided Risk & Safety doc context. "
    "Cite the Risk & Safety name and page number when possible. "
    "If the answer is not in the context, say you cannot find it in the available policies. "
    "Be clear, professional, and concise."
)
```

### Template to customise:
```python
SYSTEM_PROMPT = (
    "You are the TRU [AGENT NAME] — [one-sentence role description]. "
    "Answer questions using ONLY the information from the provided documents. "
    "Cite the document name and section when possible. "
    "If the answer is not in the provided context, say you cannot find it "
    "in the available [domain] documents — do not guess or invent information. "
    "[Any domain-specific rules, e.g. 'Always recommend speaking to a counsellor for personal crises.']"
)
```

### Example — Student Wellness Agent:
```python
SYSTEM_PROMPT = (
    "You are the TRU Wellness Advisor — a knowledgeable guide to Thompson Rivers University "
    "health, counselling, and student support services. "
    "Answer questions using ONLY the provided wellness and student services documents. "
    "Cite the service or document name when possible. "
    "If information is not in the context, acknowledge the limit and encourage the student "
    "to contact Health & Counselling directly at 250-828-5023. "
    "For any mental health crisis, always provide the BC Crisis Line (1-800-784-2433) first, "
    "before any other information. Be warm, supportive, and non-judgmental."
)
```

### Example — Course Advisor Agent:
```python
SYSTEM_PROMPT = (
    "You are the TRU Course Advisor — an expert on Thompson Rivers University academic programs, "
    "course requirements, and degree planning. "
    "Answer questions using ONLY the provided course calendar and program guide documents. "
    "Cite the program name, course code, and calendar year when answering prerequisite questions. "
    "If a course or program is not covered in the provided documents, say so clearly rather than guessing. "
    "Be precise about credit hours, prerequisites, and graduation requirements."
)
```

---

## 3 — `frontend/chatbot.js` — Widget Identity

There are **9 locations** where "Risk & Safety Assistant" (or agent-specific text) appears. Search for the current agent name and replace all at once, OR update each section below:

### 3a — File header comment (line ~2)
```js
// TRU [Agent Name] Widget
```

### 3b — Aria labels on FAB and close buttons (lines ~67, ~79, ~219, ~229)
```js
button.setAttribute('aria-label', 'Open TRU [Agent Name]');
// ...
closeBtn.setAttribute('aria-label', 'Close TRU [Agent Name]');
```

### 3c — Chat window header title (line ~85)
```js
nameEl.id = 'tru-chat-header-name';
nameEl.textContent = 'TRU [Agent Name]';
```

### 3d — Welcome message heading (line ~152)
```js
welcomeH3.textContent = 'TRU [Agent Name]';
welcomeP.textContent  = '[One-sentence description of what this agent helps with]';
```

### 3e — Quick reply buttons (near top of file, `QUICK_REPLIES` array)
These are the pre-populated question chips shown on first open. Change them to reflect the domain:

```js
// Policy Assistant 
const QUICK_REPLIES = [
  'What is the records destruction policy?',
  'Travel expense reimbursement rules?',
  'Conflict of interest policy for employees?',
  'What is the academic integrity policy?',
  'Purchasing process and approval limits?'
];

// Wellness Agent example
const QUICK_REPLIES = [
  'How do I access counselling services?',
  'What mental health support is available?',
  'How does the student health plan work?',
  'What are recreation centre hours and fees?',
  'I\'m struggling — where can I get help?'
];

// Course Advisor example
const QUICK_REPLIES = [
  'What are the prerequisites for COMP 3701?',
  'What programs offer Data Science?',
  'How many credits to graduate with a BSCS?',
  'Can I take an elective as a free elective?',
  'What is the difference between a major and a minor?'
];
```

### 3f — Error message footer (line ~361)
```js
footer.textContent = 'Source: TRU [Agent Name] · AI-generated answer';
```

### 3g — Meta attribution label (line ~398)
```js
sourceEl.textContent = 'TRU [Agent Name]';
```

---

## 4 — `frontend/index.html` — Host Page

The host page is purely presentational — the chatbot widget loads itself via `chatbot.js` regardless of which page it is on. You only need to:

1. Change the `<title>` tag and page headings to match the new agent's domain.
2. Update the hero text, breadcrumb, sidebar nav links, and service cards.
3. Update the right-sidebar CTA labels (e.g. "Ask Wellness Advisor", "Browse Health Services").
4. Keep `<script src="/static/chatbot.js"></script>` at the bottom of `<body>` — that is the only wiring needed.

The chatbot FAB and window inject themselves into the DOM automatically.

---

## 5 — `app/server.py` — FastAPI Metadata (optional)

Line ~29: `title="TRU Risk & Safety Assistant"` — this only affects the auto-generated API docs at `/docs`. Change it for cleanliness:

```python
app = FastAPI(title="TRU Wellness Advisor")
```

---

## 6 — Data Ingestion

### Step 1 — Add documents
Drop PDFs into the `data/` folder (or a sub-folder if `DATA_DIR` points to one):

```
data/
  wellness/
    TRU-Health-Services-Guide-2025.pdf
    Student-Insurance-Handbook.pdf
    Counselling-Services-FAQ.pdf
    Recreation-Services-Guide.pdf
    Peer-Support-Program.pdf
```

### Step 2 — Ingest with fresh collection
```bash
python ingest.py --fresh
```

The `--fresh` flag drops and recreates the ChromaDB collection specified in `config.py` (`COLLECTION_NAME`). **Always use `--fresh` when switching agents** or adding documents to avoid stale vectors.

Expect output like:
```
Cleared collection 'wellness_docs'
Loaded 124 total chunks from 5 files
Ingestion complete.
```

### Step 3 — Restart the server
```bash
python run.py
```

---

## 7 — Running Multiple Agents Simultaneously

To run the Risk & Safety Assistant and Wellness Advisor at the same time (different ports), override settings with environment variables:

**Windows PowerShell:**
```powershell
# Window 1 — Policy Assistant on port 8000
$env:COLLECTION_NAME="policy_docs"; $env:DATA_DIR="data/policy"; python run.py

# Window 2 — Wellness Advisor on port 8001
$env:COLLECTION_NAME="wellness_docs"; $env:DATA_DIR="data/wellness"; $env:PORT="8001"; python run.py
```

Each server is fully independent with its own collection and persona.

---

## 8 — Full Checklist for a New Agent

Use this checklist every time you create a new agent:

```
AGENT NAME: ________________________

Data & Collection
[ ] Create data sub-folder: data/[agent-name]/
[ ] Add relevant PDFs to that folder
[ ] Update COLLECTION_NAME in app/config.py
[ ] Update DATA_DIR in app/config.py
[ ] Run: python ingest.py --fresh
[ ] Verify chunk count in ingest output

Persona
[ ] Update SYSTEM_PROMPT in app/rag_core.py
[ ] Test 2–3 domain questions against the API directly

Widget (chatbot.js)
[ ] Update QUICK_REPLIES array (5 domain questions)
[ ] Update widget header title (nameEl.textContent)
[ ] Update welcome h3 + welcome paragraph
[ ] Update aria-labels on FAB and close buttons
[ ] Update error footer text
[ ] Update meta attribution label

Host Page (index.html)
[ ] Update <title> and <h1>/<h2> headings
[ ] Update hero banner text
[ ] Update breadcrumb
[ ] Update sidebar nav links
[ ] Update service cards (titles + descriptions)
[ ] Update right-sidebar CTA labels
[ ] Confirm <script src="/static/chatbot.js"></script> present in <body>

Optional
[ ] Update app/server.py FastAPI title
[ ] Update app/__init__.py docstring
[ ] Update README.md
```

---

## 9 — Domain-Specific Notes

### Student Wellness Agent
- **Data sources**: Health & Counselling Services guide, Student Health & Dental Plan booklet, Recreation Services schedule, Peer Support handbook, Mental Health resources, SafeTalk/ASIST program info.
- **Key system prompt rules**: Always surface crisis line numbers before any other content. Never diagnose or prescribe. Encourage in-person follow-ups.
- **Quick replies focus**: Access pathways, appointment booking, insurance coverage, recreational activities.
- **COLLECTION_NAME**: `"wellness_docs"`

### Course Advisor Agent
- **Data sources**: Current Academic Calendar (full PDF), Program guides for each faculty, Course prerequisite charts, Graduation requirement sheets, Transfer credit equivalency tables.
- **Key system prompt rules**: Always cite the calendar year. Warn that prerequisites change annually. Direct complex advising questions to a human academic advisor.
- **Quick replies focus**: Prerequisites, credit hours, graduation requirements, course equivalencies, program comparisons.
- **COLLECTION_NAME**: `"course_docs"`
- **Note**: The Academic Calendar PDF is large — ingestion may produce 2,000+ chunks. Increase `K` (retrieval count) to 10–12 for better coverage.

### IT Help Desk Agent
- **Data sources**: TRU IT policy documents, Acceptable Use Policy, Password & MFA guides, Service desk knowledgebase exports (PDF), Network access procedures.
- **Key system prompt rules**: Never ask users for passwords. Always recommend contacting IT directly for account lockouts.
- **COLLECTION_NAME**: `"it_docs"`
