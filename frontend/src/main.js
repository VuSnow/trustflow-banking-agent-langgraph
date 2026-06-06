import { h, render } from "https://esm.sh/preact@10.24.3";
import { useEffect, useMemo, useRef, useState } from "https://esm.sh/preact@10.24.3/hooks";
import { marked } from "https://esm.sh/marked@15.0.7";
import createDOMPurify from "https://esm.sh/dompurify@3.1.6";
import {
  Archive,
  Bot,
  Check,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Trash2,
  UserRound,
} from "https://esm.sh/lucide-preact@0.468.0";
import {
  createSession,
  deleteSession,
  getSession,
  listSessions,
  sendChatMessage,
  updateSession,
} from "./api.js";
import { formatDate, previewTitle } from "./utils.js";

const e = h;
const DOMPurify = createDOMPurify(window);

marked.setOptions({
  breaks: true,
  gfm: true,
});

function renderMarkdown(value) {
  const html = marked.parse(value || "", { async: false });
  return DOMPurify.sanitize(html);
}

function IconButton({ title, onClick, children, kind = "ghost", disabled = false }) {
  return e(
    "button",
    { class: `icon-button ${kind}`, title, "aria-label": title, onClick, disabled },
    children,
  );
}

function Spinner() {
  return e("span", { class: "spinner", "aria-hidden": "true" });
}

function SessionSkeletonRow() {
  return e(
    "div",
    { class: "session-row skeleton", "aria-hidden": "true" },
    e("span", { class: "skeleton-line skeleton-title" }),
    e("span", { class: "skeleton-line skeleton-subtitle" }),
    e("span", { class: "skeleton-line skeleton-subtitle short" }),
  );
}

function mergeSession(list, session) {
  const filtered = list.filter((item) => item.session_id !== session.session_id);
  return [session, ...filtered];
}

function removeSession(list, sessionId) {
  return list.filter((item) => item.session_id !== sessionId);
}

function syncSession(list, session) {
  if (!session) return list;
  return list.map((item) => (item.session_id === session.session_id ? { ...item, ...session } : item));
}

function Sidebar({
  userId,
  setUserId,
  sessions,
  activeId,
  onRefresh,
  onCreate,
  onOpen,
  loading = false,
  creating = false,
  disabled = false,
}) {
  return e(
    "aside",
    { class: "sidebar" },
    e("div", { class: "brand" }, e("h1", null, "TrustFlow"), e("p", null, "Banking assistant sessions")),
    e(
      "div",
      { class: "user-strip" },
      e(UserRound, { size: 18 }),
      e("input", {
        value: userId,
        onInput: (event) => setUserId(event.currentTarget.value),
        placeholder: "user id",
      }),
    ),
    e(
      "div",
      { class: "toolbar" },
      e(
        IconButton,
        { title: "New session", kind: "primary", onClick: onCreate, disabled: loading || creating || disabled },
        creating ? e(Spinner) : e(MessageSquarePlus, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Refresh sessions", onClick: onRefresh, disabled: loading || creating || disabled },
        loading ? e(Spinner) : e(RefreshCw, { size: 18 }),
      ),
    ),
    e(
      "div",
      { class: "sidebar-count" },
      loading && sessions.length === 0
        ? "Loading sessions..."
        : `${sessions.length} session${sessions.length === 1 ? "" : "s"}`,
    ),
    e(
      "div",
      { class: "session-list" },
      loading && sessions.length === 0
        ? Array.from({ length: 4 }, (_, index) => e(SessionSkeletonRow, { key: index }))
        : sessions.map((session) =>
            e(
              "button",
              {
                key: session.session_id,
                class: `session-row ${session.session_id === activeId ? "active" : ""}`,
                onClick: () => onOpen(session.session_id),
                disabled: loading || disabled,
              },
              e("span", { class: "session-title" }, previewTitle(session)),
              e("span", { class: "session-subtitle" }, `${session.message_count || 0} messages`),
              e("span", { class: "session-subtitle" }, formatDate(session.updated_at)),
            ),
          ),
    ),
  );
}

function Topbar({ session, title, setTitle, onRename, onDelete, loading = false, saving = false }) {
  return e(
    "header",
    { class: "topbar" },
    e(
      "div",
      { class: "session-heading" },
      e("h2", null, session ? previewTitle(session) : "Select a session"),
      e(
        "p",
        null,
        session
          ? `${session.session_id} | ${session.message_count || 0} messages | ${formatDate(session.updated_at)}`
          : "Create or choose a session to begin.",
      ),
    ),
    e(
      "div",
      { class: "title-tools" },
      e("input", {
        value: title,
        onInput: (event) => setTitle(event.currentTarget.value),
        placeholder: "Session title",
        disabled: !session || loading || saving,
      }),
      e(
        IconButton,
        { title: "Save title", onClick: () => onRename(), disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Check, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Archive session", onClick: () => onRename("archived"), disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Archive, { size: 18 }),
      ),
      e(
        IconButton,
        { title: "Delete session", kind: "danger", onClick: onDelete, disabled: !session || loading || saving },
        saving ? e(Spinner) : e(Trash2, { size: 18 }),
      ),
    ),
  );
}

function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const payload = message.data ? JSON.stringify(message.data, null, 2) : null;
  return e(
    "article",
    { class: `message ${isUser ? "user" : "assistant"} ${message.pending ? "pending" : ""}` },
    e(
      "div",
      { class: "message-meta" },
      e("span", null, isUser ? "You" : "TrustFlow"),
      message.pending ? e("span", { class: "message-status" }, "Loading...") : null,
      e("span", null, formatDate(message.created_at)),
    ),
    message.pending
      ? e("div", { class: "message-text pending-text" }, message.message)
      : e("div", {
          class: "message-text",
          dangerouslySetInnerHTML: { __html: renderMarkdown(message.message) },
        }),
    payload ? e("details", null, e("summary", null, "Response data"), e("pre", null, payload)) : null,
  );
}

function MessageList({ messages, activeSessionId, loading = false }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [messages.length, activeSessionId]);

  return e(
    "section",
    { class: "messages", ref },
    !activeSessionId
      ? e("div", { class: "empty-state" }, e(Bot, { size: 34 }), e("h3", null, "No session selected"))
      : loading && messages.length === 0
        ? e(
            "div",
            { class: "empty-state loading-state" },
            e(Spinner),
            e("h3", null, "Loading conversation"),
            e("p", null, "Fetching the latest messages."),
          )
      : messages.length === 0
        ? e("div", { class: "empty-state" }, e(Bot, { size: 34 }), e("h3", null, "Start the conversation"))
        : messages.map((message) => e(MessageBubble, { key: message.id || `${message.role}-${message.created_at}`, message })),
  );
}

function Composer({ disabled, onSend, loading = false }) {
  const [value, setValue] = useState("");

  async function submit() {
    const message = value.trim();
    if (!message) return;
    setValue("");
    await onSend(message);
  }

  return e(
    "footer",
    { class: "composer" },
    e("textarea", {
      value,
      disabled,
      placeholder: disabled ? "Create or select a session first" : "Ask TrustFlow...",
      onInput: (event) => setValue(event.currentTarget.value),
      onKeyDown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          submit();
        }
      },
    }),
    e(
      IconButton,
      { title: "Send", kind: "primary", disabled, onClick: submit },
      loading ? e(Spinner) : e(Send, { size: 18 }),
    ),
  );
}

function App() {
  const [userId, setUserId] = useState("u1");
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [title, setTitle] = useState("");
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isSessionLoading, setIsSessionLoading] = useState(false);
  const [busyAction, setBusyAction] = useState(null);
  const [error, setError] = useState("");
  const listRequestIdRef = useRef(0);
  const sessionRequestIdRef = useRef(0);
  const sendRequestIdRef = useRef(0);

  const canSend = useMemo(() => Boolean(activeSessionId && !busyAction && !isSessionLoading), [activeSessionId, busyAction, isSessionLoading]);

  function syncActiveSession(nextSession) {
    setActiveSession((current) => (current ? { ...current, ...nextSession } : nextSession));
    setTitle(nextSession?.title || "");
    setSessions((current) => syncSession(current, nextSession));
  }

  function appendPendingMessages(messageText, requestId) {
    const now = new Date().toISOString();
    const userTempId = `pending-user-${requestId}`;
    const assistantTempId = `pending-assistant-${requestId}`;
    setMessages((current) => [
      ...current,
      {
        id: userTempId,
        role: "user",
        message: messageText,
        created_at: now,
        pending: true,
      },
      {
        id: assistantTempId,
        role: "assistant",
        message: "TrustFlow is generating a reply...",
        created_at: now,
        pending: true,
      },
    ]);
    return { userTempId, assistantTempId };
  }

  function settlePendingMessages({ userTempId, assistantTempId, response, messageText }) {
    const now = new Date().toISOString();
    const assistantMessage = {
      id: `assistant-${assistantTempId}`,
      role: "assistant",
      message: response?.message || "No response returned.",
      data: response,
      created_at: now,
    };
    setMessages((current) =>
      current
        .map((item) => {
          if (item.id === userTempId) {
            return {
              ...item,
              pending: false,
              message: messageText,
              created_at: item.created_at || now,
            };
          }
          if (item.id === assistantTempId) {
            return assistantMessage;
          }
          return item;
        })
        .filter((item) => item.id !== userTempId || item.message || item.pending)
        .filter((item) => item.id !== assistantTempId || item.message),
    );
  }

  function clearPendingMessages(userTempId, assistantTempId) {
    setMessages((current) => current.filter((item) => item.id !== userTempId && item.id !== assistantTempId));
  }

  async function refreshSessions({ silent = false } = {}) {
    const currentUserId = userId.trim();
    if (!currentUserId) {
      setSessions([]);
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setIsLoadingSessions(false);
      return [];
    }

    const requestId = ++listRequestIdRef.current;
    if (!silent) {
      setIsLoadingSessions(true);
    }
    setError("");
    try {
      const data = await listSessions(currentUserId);
      if (requestId !== listRequestIdRef.current) return data;
      setSessions(data);
      if (activeSessionId) {
        const matched = data.find((session) => session.session_id === activeSessionId);
        if (matched) {
          setActiveSession((current) => (current ? { ...current, ...matched } : matched));
          if (!title.trim()) setTitle(matched.title || "");
        }
      }
      return data;
    } finally {
      if (requestId === listRequestIdRef.current && !silent) {
        setIsLoadingSessions(false);
      }
    }
  }

  async function openSession(sessionId) {
    const requestId = ++sessionRequestIdRef.current;
    const preview = sessions.find((session) => session.session_id === sessionId) || null;
    setActiveSessionId(sessionId);
    setActiveSession(preview ? { ...preview } : { session_id: sessionId });
    setMessages([]);
    setTitle(preview?.title || "");
    setIsSessionLoading(true);
    setError("");
    try {
      const detail = await getSession(sessionId);
      if (requestId !== sessionRequestIdRef.current) return;
      setActiveSession(detail);
      setMessages(detail.messages || []);
      setTitle(detail.title || "");
      setSessions((current) => syncSession(current, detail));
    } finally {
      if (requestId === sessionRequestIdRef.current) {
        setIsSessionLoading(false);
      }
    }
  }

  async function handleCreate() {
    setBusyAction("create");
    try {
      listRequestIdRef.current += 1;
      const session = await createSession(userId.trim(), title.trim() || null);
      setSessions((current) => mergeSession(current, session));
      setActiveSessionId(session.session_id);
      setActiveSession(session);
      setMessages([]);
      setTitle(session.title || "");
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRename(status) {
    if (!activeSessionId) return;
    setBusyAction("save");
    try {
      listRequestIdRef.current += 1;
      const payload = { title: title.trim() || activeSession?.title || activeSessionId };
      if (status) payload.status = status;
      const session = await updateSession(activeSessionId, payload);
      syncActiveSession(session);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDelete() {
    if (!activeSessionId || !confirm("Delete this session and all messages?")) return;
    setBusyAction("delete");
    try {
      listRequestIdRef.current += 1;
      await deleteSession(activeSessionId);
      const deletedId = activeSessionId;
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setSessions((current) => removeSession(current, deletedId));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSend(message) {
    if (!activeSessionId) return;
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return;
    const requestId = ++sendRequestIdRef.current;
    const pendingIds = appendPendingMessages(trimmedMessage, requestId);
    setBusyAction("send");
    setError("");
    try {
      listRequestIdRef.current += 1;
      const response = await sendChatMessage({ userId: userId.trim(), sessionId: activeSessionId, message: trimmedMessage });
      if (requestId !== sendRequestIdRef.current) return;
      settlePendingMessages({ ...pendingIds, response, messageText: trimmedMessage });
      setActiveSession((current) =>
        current
          ? {
              ...current,
              updated_at: new Date().toISOString(),
              last_message_at: new Date().toISOString(),
              message_count: (current.message_count || 0) + 2,
            }
          : current,
      );
      setSessions((current) =>
        current.map((session) =>
          session.session_id === activeSessionId
            ? {
                ...session,
                updated_at: new Date().toISOString(),
                last_message_at: new Date().toISOString(),
                message_count: (session.message_count || 0) + 2,
              }
            : session,
        ),
      );
      refreshSessions({ silent: true }).catch((err) => setError(err.message));
    } catch (err) {
      clearPendingMessages(pendingIds.userTempId, pendingIds.assistantTempId);
      setError(err.message);
    } finally {
      if (requestId === sendRequestIdRef.current) {
        setBusyAction(null);
      }
    }
  }

  useEffect(() => {
    const trimmed = userId.trim();
    if (!trimmed) {
      listRequestIdRef.current += 1;
      sessionRequestIdRef.current += 1;
      sendRequestIdRef.current += 1;
      setSessions([]);
      setActiveSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setTitle("");
      setIsLoadingSessions(false);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      refreshSessions().catch((err) => setError(err.message));
    }, 250);

    return () => window.clearTimeout(timeoutId);
  }, [userId]);

  function handleRefreshClick() {
    refreshSessions().catch((err) => setError(err.message));
  }

  function handleOpenSession(sessionId) {
    openSession(sessionId).catch((err) => setError(err.message));
  }

  return e(
    "main",
    { class: "app-shell" },
    e(Sidebar, {
      userId,
      setUserId,
      sessions,
      activeId: activeSessionId,
      onRefresh: handleRefreshClick,
      onCreate: handleCreate,
      onOpen: handleOpenSession,
      loading: isLoadingSessions,
      creating: busyAction === "create",
      disabled: Boolean(busyAction),
    }),
    e(
      "section",
      { class: "workspace" },
      e(Topbar, {
        session: activeSession,
        title,
        setTitle,
        onRename: handleRename,
        onDelete: handleDelete,
        loading: isSessionLoading,
        saving: busyAction === "save" || busyAction === "delete",
      }),
      error ? e("div", { class: "error-banner" }, error) : null,
      e(MessageList, { messages, activeSessionId, loading: isSessionLoading }),
      e(Composer, { disabled: !canSend || busyAction === "send", onSend: handleSend, loading: busyAction === "send" }),
    ),
  );
}

render(e(App), document.getElementById("app"));
