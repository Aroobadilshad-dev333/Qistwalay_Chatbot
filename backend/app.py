"""
app.py  --  FastAPI backend for the Qistwalay chatbot (Step 4)

Start it (from the qistwalay-database folder):
    uvicorn app:app --reload

Then open  http://127.0.0.1:8000/docs  to try it in the browser.

The React frontend sends:   POST /chat   {"question": "...", "chat_history": [...]}
and gets back:              {"answer": "..."}

The server does NOT remember conversations. The frontend keeps the history and sends
it with every request.
"""

import traceback
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pipeline import run_pipeline  # the existing, tested pipeline: nothing is rebuilt

app = FastAPI(title="Qistwalay Chatbot API")

# CORS: lets a React app running on another address (e.g. localhost:3000) call this API.
# For deployment this list will be replaced with the real website address.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React (Create React App)
        "http://localhost:5173",   # React (Vite)
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    chat_history: List[ChatMessage] = Field(default_factory=list, max_length=40)


class ChatResponse(BaseModel):
    answer: str


@app.get("/health")
def health():
    """Quick check that the server is running."""
    return {"status": "ok"}


# A normal (not async) function on purpose: run_pipeline is blocking, so FastAPI runs
# it in a worker thread and other requests are not frozen meanwhile.
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    history = [m.model_dump() for m in request.chat_history]
    try:
        result = run_pipeline(request.question, history)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")
    return ChatResponse(answer=result["answer"])