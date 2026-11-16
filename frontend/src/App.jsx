import { useEffect, useRef, useState } from "react";
import "./App.css";

// Use the same-origin API path in development and behind the production proxy.
const API_URL = import.meta.env.VITE_API_URL || "/api/chat";
const MAX_HISTORY = 20; // how many earlier messages are sent with each question
const CHAT_STORAGE_KEY = "qistwalay-chats";
const EMPTY_MESSAGES = [];

const EXAMPLES = [
  "What documents do I need to apply for installments?",
  "What is the maximum tenure for an Air Conditioner?",
  "Mujhe batao Refrigerator ki price range kya hai?",
];

// The assistant sometimes writes **bold**; show it as bold text.
function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.length > 4 && part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      part
    )
  );
}

function Message({ message }) {
  const kind =
    message.role === "user" ? "msg-user" : message.error ? "msg-bot msg-error" : "msg-bot";
  return (
    <div className={`msg ${kind}`}>
      {/* dir="auto" lets Urdu-script text flow right-to-left by itself */}
      <p className="msg-text" dir="auto">
        {renderInline(message.content)}
      </p>
    </div>
  );
}

function createChatId() {
  return (
    globalThis.crypto?.randomUUID?.() ||
    `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

function readChats() {
  try {
    const stored = localStorage.getItem(CHAT_STORAGE_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) throw new Error("Saved chats must be an array.");

    return parsed
      .filter(
        (chat) =>
          chat &&
          typeof chat.id === "string" &&
          typeof chat.title === "string" &&
          typeof chat.updatedAt === "string" &&
          Array.isArray(chat.messages)
      )
      .map((chat) => ({
        ...chat,
        messages: chat.messages.filter(
          (message) =>
            message &&
            ["user", "assistant"].includes(message.role) &&
            typeof message.content === "string"
        ),
      }))
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  } catch (err) {
    console.error("Couldn't read saved chats from localStorage.", err);
    return [];
  }
}

function createChatTitle(question) {
  const title = question.trim();
  return title.length > 30 ? `${title.slice(0, 30).trimEnd()}...` : title;
}

export default function App() {
  const [initialChats] = useState(readChats);
  const [chats, setChats] = useState(initialChats);
  const [activeChatId, setActiveChatId] = useState(
    () => initialChats[0]?.id || createChatId()
  );
  const [loadingChatId, setLoadingChatId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [input, setInput] = useState("");
  const messages = chats.find((chat) => chat.id === activeChatId)?.messages ?? EMPTY_MESSAGES;
  const loading = loadingChatId !== null;
  const activeChatIsLoading = loadingChatId === activeChatId;
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(chats));
    } catch (err) {
      console.error("Couldn't save chats to localStorage.", err);
    }
  }, [chats]);

  // keep the newest message in view
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, loading]);

  // let the text box grow with the text (up to a limit)
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  async function sendMessage(text) {
    const question = text.trim();
    if (!question || loading) return;

    const chatId = activeChatId;
    const userMessage = { role: "user", content: question };

    // The server remembers nothing, so we send the earlier messages every time.
    const history = messages
      .filter((m) => !m.error)
      .slice(-MAX_HISTORY)
      .map((m) => ({ role: m.role, content: m.content }));

    setChats((prev) => {
      const current = prev.find((chat) => chat.id === chatId);
      const updatedChat = {
        id: chatId,
        title: current?.title || createChatTitle(question),
        messages: [...(current?.messages || []), userMessage],
        updatedAt: new Date().toISOString(),
      };
      return [updatedChat, ...prev.filter((chat) => chat.id !== chatId)];
    });
    setInput("");
    setLoadingChatId(chatId);

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, chat_history: history }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === chatId
            ? {
                ...chat,
                messages: [...chat.messages, { role: "assistant", content: data.answer }],
                updatedAt: new Date().toISOString(),
              }
            : chat
        )
      );
    } catch (err) {
      console.error(err);
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === chatId
            ? {
                ...chat,
                messages: [
                  ...chat.messages,
                  {
                    role: "assistant",
                    error: true,
                    content:
                      "Couldn't reach the Qistwalay server. Check that the backend is running, then send your question again.",
                  },
                ],
                updatedAt: new Date().toISOString(),
              }
            : chat
        )
      );
    } finally {
      setLoadingChatId(null);
      inputRef.current?.focus();
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    sendMessage(input);
  }

  function handleKeyDown(e) {
    // Enter sends, Shift+Enter makes a new line
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function newChat() {
    setActiveChatId(createChatId());
    setInput("");
    setSidebarOpen(false);
  }

  function deleteChat(chatId) {
    const remaining = chats.filter((chat) => chat.id !== chatId);
    setChats(remaining);
    if (activeChatId === chatId) {
      setActiveChatId(remaining[0]?.id || createChatId());
    }
  }

  return (
    <div className={`app${sidebarOpen ? " sidebar-open" : ""}`}>
      <aside className="chat-sidebar" aria-label="Chat history">
        <div className="sidebar-heading">
          <h2>Recents</h2>
          <button type="button" className="new-chat" onClick={newChat}>
            + New chat
          </button>
        </div>
        <div className="chat-list">
          {chats.map((chat) => (
            <div
              className={`chat-item${chat.id === activeChatId ? " active" : ""}`}
              key={chat.id}
            >
              <button
                type="button"
                className="chat-select"
                onClick={() => {
                  setActiveChatId(chat.id);
                  setSidebarOpen(false);
                }}
                aria-current={chat.id === activeChatId ? "page" : undefined}
                title={chat.title}
              >
                {chat.title}
              </button>
              <button
                type="button"
                className="delete-chat"
                onClick={() => deleteChat(chat.id)}
                aria-label={`Delete chat: ${chat.title}`}
                title="Delete chat"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>
      {sidebarOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close chat history"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <div className="workspace">
        <header className="top">
          <div className="top-inner">
            <button
              type="button"
              className="sidebar-toggle"
              onClick={() => setSidebarOpen((open) => !open)}
              aria-expanded={sidebarOpen}
              aria-label={sidebarOpen ? "Close chat history" : "Open chat history"}
            >
              ☰
            </button>
            <div>
              <h1>Qistwalay</h1>
              <p>Installment help: plans, eligibility and products</p>
            </div>
            <button type="button" className="ghost" onClick={newChat}>
              New chat
            </button>
          </div>
        </header>

        <main className="thread" aria-live="polite">
          <div className="column">
            {messages.length === 0 && (
              <section className="empty">
                <h2>Ask about plans, eligibility or products</h2>
                <p>Write in English or Roman Urdu. You can start with one of these:</p>
                <ul>
                  {EXAMPLES.map((q) => (
                    <li key={q}>
                      <button type="button" className="example" onClick={() => sendMessage(q)}>
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {messages.map((m, i) => (
              <Message key={`${activeChatId}-${i}`} message={m} />
            ))}

            {activeChatIsLoading && (
              <div className="msg msg-bot">
                <span className="dots" role="status" aria-label="Qistwalay is typing">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </main>

        <footer className="composer">
          <form className="column composer-row" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              maxLength={1000}
              placeholder="Ask a question"
              aria-label="Your question"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              dir="auto"
            />
            <button type="submit" className="send" disabled={loading || !input.trim()}>
              Send
            </button>
          </form>
          <p className="note">Applicant figures come from a sample dataset, not real customers.</p>
        </footer>
      </div>
    </div>
  );
}