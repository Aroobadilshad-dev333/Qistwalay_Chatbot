# Qistwalay Installment Chatbot

A full-stack AI chatbot for answering questions about Qistwalay products, installment plans, website information, and a synthetic applicant dataset. The application combines retrieval-augmented generation (RAG) with read-only natural-language-to-SQL and routes each question to the appropriate source.

> **Data note:** Website content is stored as a scraped snapshot, not fetched live for every question. Applicant records are synthetic sample data, not real customer data or official policy.

## Features

| Feature | Description |
| --- | --- |
| RAG website Q&A | Retrieves product, installment, FAQ, policy, contact, and homepage content from a local FAISS index. |
| Natural-language SQL | Converts supported sample-applicant questions to guarded, read-only SQLite queries. |
| Smart routing | Routes questions to SQL, RAG, or both for mixed questions. |
| Multi-turn chat | Rephrases follow-ups using recent conversation history. |
| Grounded answers | Uses retrieved documents and query results with rules against unsupported prices, plans, and eligibility claims. |
| English and Roman Urdu | Handles English and Roman Urdu questions and answers; Urdu-script input is also supported. |
| Chat history | The React app keeps conversations in browser `localStorage` and sends recent turns with each request. |
| Responsive interface | React + Vite chat UI with right-to-left text handling for Urdu. |
| Local deployment | Docker Compose runs FastAPI and serves the frontend through nginx. |

## Architecture

```text
React + Vite chat UI
  ├─ Local chat history (browser localStorage)
  └─ POST /api/chat with question and recent history
          │
          ▼
      nginx proxy
          │
          ▼
      FastAPI /chat
          │
          ▼
      Custom Python pipeline
      conversation handling → follow-up rephrasing → question routing
          ├─ SQL → OpenAI Text-to-SQL → read-only SQLite sample database
          ├─ RAG → OpenAI embeddings → FAISS retrieval → keyword reranking
          └─ SQL and RAG for mixed questions
                    │
                    ▼
            GPT-4o-mini grounded response
```

The orchestration is implemented in the project’s Python pipeline; it does not use LangChain or LangGraph.

### Request flow

1. The frontend sends the current question and recent messages to FastAPI.
2. The pipeline recognizes conversation-related questions and rephrases ambiguous follow-ups when needed.
3. The router selects SQL, RAG, or both.
4. SQL questions query the synthetic applicant database using read-only SQLite connections. RAG questions retrieve from the local website snapshot using FAISS and lexical reranking.
5. The final model writes a response grounded in the returned data and applicable guardrails.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| LLM | OpenAI GPT-4o-mini |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector search | FAISS with keyword-overlap reranking |
| Structured data | SQLite, read-only query connections |
| Frontend | React, Vite, CSS |
| Data collection | Python `requests`, BeautifulSoup |
| Deployment | Docker Compose, nginx |

The runtime RAG lookup currently contains **2,781 chunks**. The index and its matching chunk lookup are loaded from `backend/rag/`.

## Project structure

```text
qistwalay-app/
├── backend/
│   ├── app.py                         # FastAPI /chat and /health endpoints
│   ├── pipeline.py                    # Pipeline orchestration and grounded answers
│   ├── router.py                      # SQL / RAG / both routing
│   ├── rephraser.py                   # Follow-up question rephrasing
│   ├── text2sql_module.py             # SQL generation, validation, read-only execution
│   ├── qistwalay_eligibility.db       # Runtime synthetic applicant database
│   ├── rag/
│   │   ├── chatbot_agent.py           # Embeddings, FAISS retrieval, reranking
│   │   ├── qistwalay_faiss.index      # Runtime vector index
│   │   └── qistwalay_chunk_lookup.json# Text chunks aligned with the index
│   ├── db_setup/                      # Synthetic CSV and SQLite builder
│   ├── data_pipeline/
│   │   ├── scrapers/                  # Website snapshot collectors
│   │   ├── processors/                # Cleaning, chunking, and index builder
│   │   └── qistwalay_data/            # Scraped and generated source artifacts
│   └── tests/                         # Routing, fallback, and end-to-end checks
├── frontend/
│   ├── src/                           # React chat UI and local history
│   ├── vite.config.js                 # Development API proxy
│   ├── nginx.conf                     # Production API reverse proxy
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

## Getting started

### Requirements

- Python 3.11+
- Node.js 22.12+ (or a compatible Node.js 20.19+ release)
- An OpenAI API key for model and embedding requests
- Docker Desktop, if using Docker Compose

### Option 1: Run with Docker Compose

1. Create `backend/.env` from the example only if it does not already exist:

   ```powershell
   if (-not (Test-Path backend\.env)) { Copy-Item .env.example backend\.env }
   ```

2. Add your own OpenAI key to `backend/.env`:

   ```dotenv
   OPENAI_API_KEY=your_openai_api_key
   ```

   Never paste a real key into source code, a frontend environment variable, or a committed file. Keep `backend/.env` private.

3. From the project root, build and start both services:

   ```powershell
   docker compose up --build
   ```

4. Open the chat at [http://localhost:8080](http://localhost:8080). The API health check is [http://localhost:8080/api/health](http://localhost:8080/api/health).

5. Stop the services with `Ctrl+C`, or run `docker compose down` in another terminal.

### Option 2: Run backend and frontend separately

Create `backend/.env` as above, then install and start the backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, configure the frontend development proxy to use that backend. Create `frontend/.env.local` with:

```dotenv
BACKEND_URL=http://127.0.0.1:8000
```

Then start the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed in the terminal (typically [http://localhost:5173](http://localhost:5173)). The frontend uses `/api/chat`; Vite proxies it to the backend’s `/chat` endpoint. Do not put OpenAI keys in `frontend/.env.local`.

### Environment variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Backend | Authenticates model and embedding requests. Required for live chat. |
| `SHOW_PRIVATE_FIELDS` | Backend | Controls whether synthetic sample CNIC, mobile, and email fields can be shown. Set to `false` to hide them. |
| `SQL_MODEL` | Backend | Optional Text-to-SQL model override; defaults to `gpt-4o-mini`. |
| `RAG_FOLDER` | Backend | Runtime RAG asset directory; defaults to `backend/rag/` locally. Docker sets it to `/app/rag`. |
| `BACKEND_URL` | Frontend dev server | Vite proxy target; defaults to `http://127.0.0.1:8001`. Set it to the backend address if using another port. |
| `VITE_API_URL` | Frontend build | Optional chat endpoint override. Normally leave unset to use the same-origin `/api/chat` proxy. |

The repository includes `.env.example` with placeholders only. Actual `.env` files are excluded from Git.

## API

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Returns API health status. |
| `POST` | `/chat` | Accepts a question and optional recent chat history; returns an answer. |

Example request:

```json
{
  "question": "What documents do I need to apply for installments?",
  "chat_history": []
}
```

Example response:

```json
{
  "answer": "..."
}
```

When using the frontend proxy, the corresponding paths are `/api/health` and `/api/chat`.

## Refreshing website data

The chatbot uses a **stored website snapshot**. Scrapers collect content from Qistwalay; they do not run automatically for each chat question. To refresh the RAG data, run commands from `backend/data_pipeline`:

```powershell
python scrapers\scrape_qistwalay.py
python processors\clean_data.py
python processors\build_rag_chunks.py
python processors\build_faiss_index.py
```

Run any needed supplementary scrapers (for homepage, deals, or installment plans) as appropriate for the data being refreshed. The chunk and index builders write artifacts to `qistwalay_data/`; copy the matching generated files to the runtime `rag/` folder before restarting or deploying:

```powershell
Copy-Item qistwalay_data\qistwalay_faiss.index ..\rag\qistwalay_faiss.index -Force
Copy-Item qistwalay_data\qistwalay_chunk_lookup.json ..\rag\qistwalay_chunk_lookup.json -Force
```

Scraping sends requests to the Qistwalay website. Index generation sends text to the OpenAI embeddings API and may incur charges. Run refresh/build steps intentionally; do not treat snapshot values as guaranteed current.

## Rebuilding the synthetic SQLite database

The sample source CSV is in `backend/db_setup/`. The builder writes the runtime database at `backend/qistwalay_eligibility.db`:

```powershell
cd backend\db_setup
python build_database.py
```

Rebuilding replaces the applicant table. Preserve the current runtime database before rebuilding if it contains changes you need.

## Tests and checks

From `backend/`, run the deterministic unit tests:

```powershell
python -m unittest discover -s tests -p test_routing_rules.py
python -m unittest discover -s tests -p test_pipeline_fallback.py
```

`tests/test_e2e.py` sends live model-backed questions and may incur API charges:

```powershell
python tests\test_e2e.py
```

From `frontend/`, run the frontend checks:

```powershell
npm run lint
npm run build
```

## Security and data limitations

- Keep `OPENAI_API_KEY` in the backend `.env` or a deployment secret manager. Never commit keys or expose them through `VITE_*` variables.
- `.env` files are gitignored; use `.env.example` only as a placeholder template.
- SQL execution uses a read-only SQLite connection and validates generated queries.
- Applicant rows are synthetic sample records, not real customers. Their stored outcomes do not determine a real person’s eligibility or represent official Qistwalay policy.
- The dataset’s previous-plan/default fields are not a ledger of actual installment transactions.
- Prices, availability, plans, and policies come from a scraped snapshot and can become outdated. Confirm current details with Qistwalay.
- Live model and embedding calls require a valid key and can incur API usage charges.

## Credits

Built as a full-stack AI application demonstrating custom LLM orchestration, RAG, vector retrieval, guarded Text-to-SQL, and React/FastAPI integration.
