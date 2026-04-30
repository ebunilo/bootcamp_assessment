const $ = (sel, root = document) => root.querySelector(sel);

const statusPill = $("#status-pill");
const btnNew = $("#btn-new-chat");
const btnSend = $("#btn-send");
const form = $("#composer");
const input = $("#msg-input");
const welcome = $("#welcome");
const messagesEl = $("#messages");

let sessionId = null;
let streaming = false;

function setStatus(text, variant = "muted") {
  statusPill.textContent = text;
  statusPill.className = "pill";
  if (variant === "live") statusPill.classList.add("pill-live");
  else if (variant === "error") statusPill.classList.add("pill-error");
  else statusPill.classList.add("pill-muted");
}

async function ensureSession() {
  if (sessionId) return sessionId;
  const res = await fetch("/api/sessions", { method: "POST" });
  if (!res.ok) throw new Error("Could not start session");
  const data = await res.json();
  sessionId = data.session_id;
  return sessionId;
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.ok) setStatus("Live · ready", "live");
    else setStatus("Not configured", "error");
  } catch {
    setStatus("Offline", "error");
  }
}

function showChatArea() {
  welcome.hidden = true;
  messagesEl.hidden = false;
}

function appendUserBubble(text) {
  showChatArea();
  const div = document.createElement("div");
  div.className = "msg msg-user";
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function appendAssistantShell() {
  showChatArea();
  const wrap = document.createElement("div");
  wrap.className = "msg-meta";
  const bubble = document.createElement("div");
  bubble.className = "msg msg-assistant";
  bubble.setAttribute("aria-live", "polite");
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { wrap, bubble };
}

function appendToolStrip(parent, name, ok, preview) {
  const strip = document.createElement("div");
  strip.className = "tool-strip" + (ok ? " ok" : " bad");
  strip.textContent = `${ok ? "✓" : "⚠"} ${name}${preview ? " · " + preview : ""}`;
  parent.appendChild(strip);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLoading(loading) {
  streaming = loading;
  btnSend.disabled = loading;
  input.disabled = loading;
  $(".btn-send-label", btnSend).hidden = loading;
  $(".btn-send-spinner", btnSend).hidden = !loading;
}

function parseSseBlocks(buffer) {
  const events = [];
  let idx;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const raw = buffer.slice(0, idx).trimEnd();
    buffer = buffer.slice(idx + 2);
    if (!raw.startsWith("data:")) continue;
    const line = raw.replace(/^data:\s?/, "");
    try {
      events.push(JSON.parse(line));
    } catch {
      /* ignore */
    }
  }
  return { events, rest: buffer };
}

async function streamChat(userText) {
  const sid = await ensureSession();
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sid, message: userText }),
  });

  if (!res.ok || !res.body) {
    const errText = await res.text().catch(() => "");
    throw new Error(errText || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let current = appendAssistantShell();
  let assistantBubble = current.bubble;

  while (true) {
    const { done, value } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: true });
    const { events, rest } = parseSseBlocks(buf);
    buf = rest;

    for (const ev of events) {
      if (ev.type === "delta" && ev.text) {
        assistantBubble.textContent += ev.text;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (ev.type === "tools_pending" && Array.isArray(ev.names)) {
        const note = document.createElement("div");
        note.className = "tool-strip";
        note.textContent = "Checking: " + ev.names.join(", ");
        current.wrap.insertBefore(note, assistantBubble.nextSibling);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (ev.type === "tool_result") {
        appendToolStrip(current.wrap, ev.name, ev.ok, ev.preview || "");
      } else if (ev.type === "error") {
        assistantBubble.textContent += (assistantBubble.textContent ? "\n\n" : "") + "Error: " + ev.message;
      } else if (ev.type === "turn_done") {
        if (ev.limited) {
          const foot = document.createElement("div");
          foot.className = "tool-strip";
          foot.textContent = "Note: tool round limit reached; reply may be incomplete.";
          current.wrap.appendChild(foot);
        }
      }
    }

    if (done) break;
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || streaming) return;
  input.value = "";
  appendUserBubble(text);
  setLoading(true);
  setStatus("Thinking…", "muted");
  try {
    await streamChat(text);
    setStatus("Live · ready", "live");
  } catch (err) {
    setStatus("Error", "error");
    const { bubble } = appendAssistantShell();
    bubble.textContent = "Something went wrong. Please try again.\n\n" + String(err.message || err);
  } finally {
    setLoading(false);
  }
});

btnNew.addEventListener("click", async () => {
  sessionId = null;
  messagesEl.innerHTML = "";
  messagesEl.hidden = true;
  welcome.hidden = false;
  setStatus("Starting…", "muted");
  try {
    await ensureSession();
    setStatus("Live · ready", "live");
  } catch {
    setStatus("Offline", "error");
  }
});

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    const msg = btn.getAttribute("data-msg");
    if (!msg) return;
    input.value = msg;
    form.requestSubmit();
  });
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

checkHealth();
ensureSession().catch(() => setStatus("Offline", "error"));
