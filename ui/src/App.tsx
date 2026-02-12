import React, { useEffect, useMemo, useRef, useState } from "react";
import { marked } from "marked";

type Note = {
  id: number;
  title: string;
  content: string;
  is_markdown: boolean;
  created_at: string;
  updated_at: string;
};

type Tag = {
  id: number;
  name: string;
};

type RagAnswer = {
  answer: string;
  thinking: string;
  sources: string[];
};

type ReindexStatus = {
  running: boolean;
  current: number;
  total: number;
  error?: string | null;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  sources?: string[];
};

type AskStage = "idle" | "send" | "embed" | "search" | "compose" | "done" | "error";

type AskStatus = {
  stage: AskStage;
  label: string;
  message?: string;
};

const ASK_STEPS: Array<{ stage: AskStage; label: string }> = [
  { stage: "send", label: "Send" },
  { stage: "embed", label: "Embed" },
  { stage: "search", label: "Search" },
  { stage: "compose", label: "Compose" },
  { stage: "done", label: "Done" },
];

const ASK_STAGE_ORDER: AskStage[] = [
  "send",
  "embed",
  "search",
  "compose",
  "done",
  "error",
];

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8765";

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

function normalizeTimestamp(value: string): number {
  if (!value) return 0;
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const parsed = Date.parse(normalized);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatTimestamp(value: string): string {
  const parsed = normalizeTimestamp(value);
  if (!parsed) return value;
  return new Date(parsed).toLocaleString();
}

function toTagInput(tags: Tag[]): string {
  return tags.map((tag) => tag.name).join(", ");
}

function parseTagInput(value: string): string[] {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

function sameTags(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const left = [...a].sort();
  const right = [...b].sort();
  return left.every((value, index) => value === right[index]);
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

marked.setOptions({ breaks: true, gfm: true });

export default function App() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [selectedNoteId, setSelectedNoteId] = useState<number | null>(null);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [noteIsMarkdown, setNoteIsMarkdown] = useState(false);
  const [noteTags, setNoteTags] = useState<Tag[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [tags, setTags] = useState<Tag[]>([]);
  const [activeTagIds, setActiveTagIds] = useState<number[]>([]);
  const [tagSearch, setTagSearch] = useState("");
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"edit" | "preview" | "split">("edit");
  const [activePanel, setActivePanel] = useState<"tags" | "ask" | null>("tags");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [qnaInput, setQnaInput] = useState("");
  const [reindexStatus, setReindexStatus] = useState<ReindexStatus | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [askStatus, setAskStatus] = useState<AskStatus>({ stage: "idle", label: "Idle" });
  const [activeAssistantId, setActiveAssistantId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [appError, setAppError] = useState<string | null>(null);

  const isDirtyRef = useRef(false);
  const skipSaveRef = useRef(false);

  function togglePanel(panel: "tags" | "ask") {
    setActivePanel((prev) => (prev === panel ? null : panel));
  }

  useEffect(() => {
    let active = true;

    async function loadTags() {
      try {
        const data = await apiRequest<Tag[]>("/tags");
        if (active) setTags(data);
      } catch (error) {
        if (active) setAppError((error as Error).message);
      }
    }

    loadTags();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadNotes() {
      try {
        const query = activeTagIds.length ? `?tag_ids=${activeTagIds.join(",")}` : "";
        const data = await apiRequest<Note[]>(`/notes${query}`);
        const sorted = [...data].sort(
          (a, b) => normalizeTimestamp(b.updated_at) - normalizeTimestamp(a.updated_at)
        );
        if (!active) return;
        setNotes(sorted);

        if (!selectedNoteId || !sorted.some((note) => note.id === selectedNoteId)) {
          setSelectedNoteId(sorted[0]?.id ?? null);
        }
      } catch (error) {
        if (active) setAppError((error as Error).message);
      }
    }

    loadNotes();

    return () => {
      active = false;
    };
  }, [activeTagIds]);

  useEffect(() => {
    let active = true;

    async function loadSelectedNote() {
      if (!selectedNoteId) {
        setNoteTitle("");
        setNoteContent("");
        setNoteIsMarkdown(false);
        setNoteTags([]);
        setTagInput("");
        return;
      }

      try {
        const note = await apiRequest<Note>(`/notes/${selectedNoteId}`);
        const tagsData = await apiRequest<Tag[]>(`/notes/${selectedNoteId}/tags`);
        if (!active) return;

        skipSaveRef.current = true;
        setNoteTitle(note.title);
        setNoteContent(note.content);
        setNoteIsMarkdown(note.is_markdown);
        setNoteTags(tagsData);
        setTagInput(toTagInput(tagsData));
        isDirtyRef.current = false;
      } catch (error) {
        if (active) setAppError((error as Error).message);
      }
    }

    loadSelectedNote();

    return () => {
      active = false;
    };
  }, [selectedNoteId]);

  useEffect(() => {
    const handler = window.setInterval(async () => {
      try {
        const status = await apiRequest<ReindexStatus>("/rag/reindex");
        setReindexStatus(status);
      } catch (error) {
        setReindexStatus(null);
      }
    }, 4000);

    return () => window.clearInterval(handler);
  }, []);

  useEffect(() => {
    if (!selectedNoteId) return;
    if (skipSaveRef.current) {
      skipSaveRef.current = false;
      return;
    }

    if (!isDirtyRef.current) return;

    setIsSaving(true);
    setSaveError(null);

    const handle = window.setTimeout(async () => {
      try {
        const payload = {
          title: noteTitle,
          content: noteContent,
          is_markdown: noteIsMarkdown,
        };
        const updated = await apiRequest<Note>(`/notes/${selectedNoteId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setNotes((prev) =>
          prev.map((note) => (note.id === updated.id ? updated : note))
        );
        isDirtyRef.current = false;
      } catch (error) {
        setSaveError((error as Error).message);
      } finally {
        setIsSaving(false);
      }
    }, 600);

    return () => window.clearTimeout(handle);
  }, [noteTitle, noteContent, noteIsMarkdown, selectedNoteId]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      if (key === "n") {
        event.preventDefault();
        handleCreateNote();
      }
      if (key === "p") {
        event.preventDefault();
        setMode((prev) => (prev === "preview" ? "edit" : "preview"));
      }
      if (key === "m") {
        event.preventDefault();
        setNoteIsMarkdown((prev) => !prev);
        isDirtyRef.current = true;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedNoteId]);

  const filteredNotes = useMemo(() => {
    if (!search.trim()) return notes;
    const term = search.trim().toLowerCase();
    return notes.filter(
      (note) =>
        note.title.toLowerCase().includes(term) ||
        note.content.toLowerCase().includes(term)
    );
  }, [notes, search]);

  const filteredTags = useMemo(() => {
    if (!tagSearch.trim()) return tags;
    const term = tagSearch.trim().toLowerCase();
    return tags.filter((tag) => tag.name.toLowerCase().includes(term));
  }, [tags, tagSearch]);

  const selectedNote = useMemo(
    () => notes.find((note) => note.id === selectedNoteId) || null,
    [notes, selectedNoteId]
  );

  const markdownHtml = useMemo(() => {
    if (!noteIsMarkdown) return "";
    return marked.parse(noteContent) as string;
  }, [noteContent, noteIsMarkdown]);

  async function handleCreateNote() {
    try {
      const created = await apiRequest<Note>("/notes", {
        method: "POST",
        body: JSON.stringify({ title: "New note", content: "", is_markdown: false }),
      });
      setNotes((prev) => [created, ...prev]);
      setSelectedNoteId(created.id);
      setNoteTitle(created.title);
      setNoteContent(created.content);
      setNoteIsMarkdown(created.is_markdown);
      setNoteTags([]);
      setTagInput("");
    } catch (error) {
      setAppError((error as Error).message);
    }
  }

  async function handleDeleteNote() {
    if (!selectedNoteId) return;
    const confirmDelete = window.confirm("Delete this note?");
    if (!confirmDelete) return;

    try {
      await apiRequest(`/notes/${selectedNoteId}`, { method: "DELETE" });
      setNotes((prev) => prev.filter((note) => note.id !== selectedNoteId));
      setSelectedNoteId(null);
    } catch (error) {
      setAppError((error as Error).message);
    }
  }

  async function handleTagCommit() {
    if (!selectedNoteId) return;
    try {
      const nextTags = parseTagInput(tagInput);
      const currentTags = noteTags.map((tag) => tag.name);
      if (sameTags(nextTags, currentTags)) return;
      const payload = { tags: nextTags };
      await apiRequest(`/notes/${selectedNoteId}/tags`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const tagsData = await apiRequest<Tag[]>(`/notes/${selectedNoteId}/tags`);
      const allTags = await apiRequest<Tag[]>("/tags");
      setNoteTags(tagsData);
      setTags(allTags);
    } catch (error) {
      setAppError((error as Error).message);
    }
  }

  async function handleAsk() {
    const question = qnaInput.trim();
    if (!question || isAsking) return;
    const userMessage: ChatMessage = {
      id: makeId(),
      role: "user",
      content: question,
    };
    const assistantId = makeId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      thinking: "",
      sources: [],
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setQnaInput("");
    setIsAsking(true);
    setAskStatus({ stage: "send", label: "Send" });
    setActiveAssistantId(assistantId);

    let doneReceived = false;

    const updateAssistant = (patch: Partial<ChatMessage>) => {
      setMessages((prev) =>
        prev.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg))
      );
    };

    const appendAssistant = (field: "content" | "thinking", delta: string) => {
      if (!delta) return;
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? { ...msg, [field]: `${msg[field] ?? ""}${delta}` }
            : msg
        )
      );
    };

    const handleSseEvent = (rawEvent: string) => {
      const lines = rawEvent.split("\n");
      let eventType = "message";
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventType = line.slice(6).trim();
        }
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }
      if (!dataLines.length) return;
      const dataText = dataLines.join("\n");
      let payload: any = dataText;
      try {
        payload = JSON.parse(dataText);
      } catch {
        payload = dataText;
      }

      if (eventType === "status") {
        const stage = (payload.stage as AskStage) || "compose";
        const label = payload.label || "Working";
        const message = payload.message || undefined;
        setAskStatus({ stage, label, message });
      }

      if (eventType === "answer") {
        appendAssistant("content", payload.delta || "");
      }

      if (eventType === "thinking") {
        appendAssistant("thinking", payload.delta || "");
      }

      if (eventType === "done") {
        doneReceived = true;
        if (payload.sources) {
          updateAssistant({ sources: payload.sources });
        }
        setAskStatus({ stage: "done", label: "Done" });
      }

      if (eventType === "error") {
        doneReceived = true;
        const message = payload.message || "Request failed.";
        setAskStatus({ stage: "error", label: "Error", message });
        updateAssistant({ content: message });
      }
    };

    try {
      const response = await fetch(`${API_BASE}/rag/ask/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question }),
      });

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text || `Request failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          handleSseEvent(rawEvent);
          boundary = buffer.indexOf("\n\n");
        }
      }

      if (!doneReceived) {
        setAskStatus({ stage: "done", label: "Done" });
      }
    } catch (error) {
      const message = (error as Error).message;
      setAskStatus({ stage: "error", label: "Error", message });
      updateAssistant({ content: message });
    } finally {
      setIsAsking(false);
    }
  }

  async function handleReindex() {
    try {
      await apiRequest("/rag/reindex", { method: "POST" });
      const status = await apiRequest<ReindexStatus>("/rag/reindex");
      setReindexStatus(status);
    } catch (error) {
      setAppError((error as Error).message);
    }
  }

  function toggleTagFilter(tagId: number) {
    setActiveTagIds((prev) =>
      prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId]
    );
  }

  function clearFilters() {
    setActiveTagIds([]);
  }

  function updateTitle(value: string) {
    setNoteTitle(value);
    isDirtyRef.current = true;
  }

  function updateContent(value: string) {
    setNoteContent(value);
    isDirtyRef.current = true;
  }

  function updateMarkdown(value: boolean) {
    setNoteIsMarkdown(value);
    isDirtyRef.current = true;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <div className="brand-title">Disco Notes</div>
            <div className="brand-subtitle">Local notes with fast recall</div>
          </div>
        </div>
        <div className="top-actions">
          <div className="search">
            <input
              type="search"
              placeholder="Search notes"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <button className="btn primary" onClick={handleCreateNote} title="New note (Ctrl+N)">
            New
          </button>
        </div>
      </header>

      {appError && <div className="banner error">{appError}</div>}

      <div className={`workspace ${activePanel ? "panel-open" : ""}`}>
        <div className="left-rail">
          <button
            className={`rail-btn ${activePanel === "tags" ? "active" : ""}`}
            onClick={() => togglePanel("tags")}
            title="Tags"
          >
            <span className="rail-icon">T</span>
          </button>
          <button
            className={`rail-btn ${activePanel === "ask" ? "active" : ""}`}
            onClick={() => togglePanel("ask")}
            title="Ask"
          >
            <span className="rail-icon">Q</span>
          </button>
        </div>

        <aside className={`left-panel ${activePanel ? "open" : ""}`}>
          {activePanel === "tags" && (
            <div className="panel-body">
              <div className="panel-header">
                <h3>Tags</h3>
                <div className="panel-actions">
                  {activeTagIds.length > 0 && (
                    <button className="btn ghost" onClick={clearFilters}>
                      Clear
                    </button>
                  )}
                  <button className="btn ghost" onClick={() => setActivePanel(null)}>
                    Close
                  </button>
                </div>
              </div>
              <div className="tag-search">
                <input
                  type="search"
                  placeholder="Filter tags"
                  value={tagSearch}
                  onChange={(event) => setTagSearch(event.target.value)}
                />
              </div>
              <div className="tag-list">
                {filteredTags.length === 0 && <div className="empty">No tags yet</div>}
                {filteredTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={`chip ${activeTagIds.includes(tag.id) ? "active" : ""}`}
                    onClick={() => toggleTagFilter(tag.id)}
                  >
                    {tag.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {activePanel === "ask" && (
            <div className="qna-panel">
              <div className="panel-header">
                <h3>
                  Ask your notes
                  {isAsking && <span className="spinner" />}
                </h3>
                <button className="btn ghost" onClick={() => setActivePanel(null)}>
                  Close
                </button>
              </div>
              <div className="qna-status">
                <div>
                  <span className="label">Index</span>
                  {reindexStatus?.running ? (
                    <span className="pill">
                      Indexing {reindexStatus.current}/{reindexStatus.total}
                    </span>
                  ) : (
                    <span className="pill">Ready</span>
                  )}
                  {reindexStatus?.error && (
                    <span className="pill error">{reindexStatus.error}</span>
                  )}
                </div>
                <button className="btn ghost" onClick={handleReindex}>
                  Reindex
                </button>
              </div>
              <div className="qna-messages">
                {messages.length === 0 && (
                  <div className="empty">Ask a question about your notes.</div>
                )}
                {messages.map((message) => (
                  <div key={message.id} className={`message ${message.role}`}>
                    <div className="message-role">
                      {message.role === "user" ? "You" : "Assistant"}
                    </div>
                    {message.role === "assistant" &&
                      message.id === activeAssistantId &&
                      askStatus.stage !== "idle" && (
                        <div className="assistant-status">
                          <div className="assistant-progress">
                            {ASK_STEPS.map((step) => {
                              const activeIndex = ASK_STAGE_ORDER.indexOf(askStatus.stage);
                              const stepIndex = ASK_STAGE_ORDER.indexOf(step.stage);
                              const isDone =
                                askStatus.stage === "done" ||
                                (askStatus.stage !== "error" && activeIndex > stepIndex);
                              if (!isDone) return null;
                              return (
                                <span
                                  key={step.stage}
                                  className="assistant-progress-dot complete"
                                  title={step.label}
                                />
                              );
                            })}
                            {askStatus.stage !== "done" && (
                              <>
                                <span
                                  className={`assistant-progress-dot ${
                                    askStatus.stage === "error" ? "error" : "active"
                                  }`}
                                  title={askStatus.label}
                                />
                                <span className="assistant-progress-label">
                                  {askStatus.label}
                                </span>
                              </>
                            )}
                          </div>
                          {askStatus.message && (
                            <span className="assistant-status-message">{askStatus.message}</span>
                          )}
                        </div>
                      )}
                    <div className="message-content">{message.content}</div>
                    {message.thinking && (
                      <details>
                        <summary>Thinking</summary>
                        <pre>{message.thinking}</pre>
                      </details>
                    )}
                    {message.sources && message.sources.length > 0 && (
                      <div className="sources">
                        <span className="label">Sources</span>
                        <ul>
                          {message.sources.map((src) => (
                            <li key={src}>{src}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="qna-input">
                <input
                  type="text"
                  placeholder="Ask anything..."
                  value={qnaInput}
                  onChange={(event) => setQnaInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      handleAsk();
                    }
                  }}
                  disabled={isAsking}
                />
                <button
                  className="btn primary"
                  onClick={handleAsk}
                  disabled={isAsking || !qnaInput.trim()}
                >
                  {isAsking ? "Thinking..." : "Send"}
                </button>
              </div>
            </div>
          )}
        </aside>

        <section className="note-list">
          <div className="panel-header">
            <h3>Notes</h3>
            <div className="pill">{filteredNotes.length}</div>
          </div>
          <div className="note-items">
            {filteredNotes.length === 0 && (
              <div className="empty">No notes yet. Create one to begin.</div>
            )}
            {filteredNotes.map((note) => (
              <button
                key={note.id}
                className={`note-card ${note.id === selectedNoteId ? "active" : ""}`}
                onClick={() => setSelectedNoteId(note.id)}
              >
                <div className="note-title">{note.title || "Untitled"}</div>
                <div className="note-meta">{formatTimestamp(note.updated_at)}</div>
                <div className="note-preview">{note.content.slice(0, 120) || "No content"}</div>
              </button>
            ))}
          </div>
        </section>

        <section className="editor">
          <div className="panel-header editor-header">
            <div className="editor-title">
              <input
                type="text"
                placeholder="Title"
                value={noteTitle}
                onChange={(event) => updateTitle(event.target.value)}
                disabled={!selectedNoteId}
              />
              <div className="meta-row">
                {selectedNote ? (
                  <span className="meta">Last updated {formatTimestamp(selectedNote.updated_at)}</span>
                ) : (
                  <span className="meta">Select a note</span>
                )}
                {isSaving && <span className="meta saving">Saving...</span>}
                {saveError && <span className="meta error">{saveError}</span>}
              </div>
            </div>
            <div className="editor-actions">
              <div className="toggle">
                <button
                  className={mode === "edit" ? "active" : ""}
                  onClick={() => setMode("edit")}
                >
                  Edit
                </button>
                <button
                  className={mode === "preview" ? "active" : ""}
                  onClick={() => setMode("preview")}
                >
                  Preview
                </button>
                <button
                  className={mode === "split" ? "active" : ""}
                  onClick={() => setMode("split")}
                >
                  Split
                </button>
              </div>
              <label className="switch" title="Toggle markdown (Ctrl+M)">
                <input
                  type="checkbox"
                  checked={noteIsMarkdown}
                  onChange={(event) => updateMarkdown(event.target.checked)}
                  disabled={!selectedNoteId}
                />
                <span>Markdown</span>
              </label>
              <button className="btn ghost" onClick={handleDeleteNote} disabled={!selectedNoteId}>
                Delete
              </button>
            </div>
          </div>

          <div className="tag-editor">
            <span className="label">Tags</span>
            <input
              type="text"
              placeholder="Add tags, separated by commas"
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onBlur={handleTagCommit}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  handleTagCommit();
                }
              }}
              disabled={!selectedNoteId}
            />
            <div className="tag-chips">
              {noteTags.map((tag) => (
                <span key={tag.id} className="chip compact">
                  {tag.name}
                </span>
              ))}
            </div>
          </div>

          {!selectedNoteId && <div className="empty">Choose a note or create a new one.</div>}

          {selectedNoteId && (
            <div className={`editor-body ${mode}`}>
              {(mode === "edit" || mode === "split") && (
                <textarea
                  value={noteContent}
                  onChange={(event) => updateContent(event.target.value)}
                  placeholder="Start writing..."
                />
              )}
              {(mode === "preview" || mode === "split") && (
                <div className="preview">
                  {noteIsMarkdown ? (
                    <div
                      className="markdown"
                      dangerouslySetInnerHTML={{ __html: markdownHtml }}
                    />
                  ) : (
                    <div className="plain">{noteContent || "No content"}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>

      </div>
    </div>
  );
}
