const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const historyList = document.getElementById("history-list");
const intentBadge = document.getElementById("intent-badge");
const modeToggle = document.getElementById("mode-toggle");
const settingsModal = document.getElementById("settings-modal");

let currentMode = "";
let conversation = [];

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function clearWelcome() {
  const welcome = chatWindow.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function appendUserMessage(text) {
  clearWelcome();
  const el = document.createElement("div");
  el.className = "msg user";
  el.textContent = text;
  chatWindow.appendChild(el);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return el;
}

function appendAssistantMessage() {
  clearWelcome();
  const el = document.createElement("div");
  el.className = "msg assistant";
  chatWindow.appendChild(el);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return el;
}

function appendTierLog() {
  clearWelcome();
  const wrap = document.createElement("div");
  wrap.className = "tier-log";
  chatWindow.appendChild(wrap);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return wrap;
}

const TIER_LABELS = {
  generator: "Generator (Kimi)",
  auditor: "Auditor (GLM)",
  deep_reasoner: "Deep Reasoner (DeepSeek)",
  syntax_verifier: "Syntax Verifier (Coder)",
  safety_net: "Safety Net (Nemotron Ultra)",
};

function upsertTierRow(wrap, event) {
  const key = event.tier;
  let row = wrap.querySelector(`[data-tier="${key}"]`);
  if (!row) {
    row = document.createElement("div");
    row.className = "tier-row";
    row.dataset.tier = key;
    row.innerHTML = `<span class="dot"></span><span class="label"></span>`;
    wrap.appendChild(row);
  }
  row.className = `tier-row ${event.status === "report" ? "done" : event.status}`;
  const label = TIER_LABELS[key] || key;
  let extra = "";
  if (event.status === "report") {
    if ("bug_count" in event) extra = ` — ${event.bug_count} bug(s) found`;
    if ("compliant" in event) extra = event.compliant ? " — compliant" : ` — ${event.issues.length} issue(s)`;
  } else if (event.status === "error") {
    extra = ` — ${event.message}`;
  }
  row.querySelector(".label").textContent = `${label}${extra}`;
}

function renderFileBlock(container, path, content) {
  const block = document.createElement("div");
  block.className = "file-block";
  block.innerHTML = `
    <div class="file-block-header">
      <span>${escapeHtml(path)}</span>
      <span>
        <button class="copy-btn">Copy</button>
        <button class="download-btn">Download</button>
      </span>
    </div>
    <pre><code>${escapeHtml(content)}</code></pre>
  `;
  block.querySelector(".copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(content);
  });
  block.querySelector(".download-btn").addEventListener("click", () => {
    const blob = new Blob([content], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = path.split("/").pop();
    a.click();
  });
  container.appendChild(block);
}

async function streamChat(message) {
  appendUserMessage(message);
  conversation.push({ role: "user", content: message });

  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history: conversation, mode: currentMode || null }),
  });

  if (!resp.ok || !resp.body) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    const el = appendAssistantMessage();
    el.textContent = `Error: ${err.detail || "request failed"}`;
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantEl = null;
  let tierWrap = null;
  let assistantText = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const eventMatch = rawEvent.match(/^event: (.+)$/m);
      const dataMatch = rawEvent.match(/^data: (.+)$/m);
      if (!eventMatch || !dataMatch) continue;
      const kind = eventMatch[1];
      const data = JSON.parse(dataMatch[1]);

      if (kind === "intent") {
        intentBadge.textContent = data.mode === "fast" ? "→ fast chat" : "→ heavy swarm";
      } else if (kind === "token") {
        if (!assistantEl) assistantEl = appendAssistantMessage();
        assistantText += data.token;
        assistantEl.textContent = assistantText;
        chatWindow.scrollTop = chatWindow.scrollHeight;
      } else if (kind === "tier") {
        if (!tierWrap) tierWrap = appendTierLog();
        upsertTierRow(tierWrap, data);
      } else if (kind === "result") {
        const filesEl = appendAssistantMessage();
        filesEl.textContent = `Swarm finished — ${Object.keys(data.files).length} file(s) generated.`;
        const container = document.createElement("div");
        container.style.display = "flex";
        container.style.flexDirection = "column";
        container.style.gap = "8px";
        container.style.marginTop = "8px";
        for (const [path, content] of Object.entries(data.files)) {
          renderFileBlock(container, path, content);
        }
        const deployRow = document.createElement("div");
        deployRow.className = "deploy-row";
        const deployBtn = document.createElement("button");
        deployBtn.textContent = "Deploy to Vercel";
        deployBtn.addEventListener("click", () => deployProject(data.id, deployBtn));
        deployRow.appendChild(deployBtn);
        container.appendChild(deployRow);
        chatWindow.appendChild(container);
        chatWindow.scrollTop = chatWindow.scrollHeight;
        loadHistory();
      } else if (kind === "error") {
        const el = appendAssistantMessage();
        el.textContent = `Error: ${data.message}`;
      } else if (kind === "done") {
        if (assistantText) conversation.push({ role: "assistant", content: assistantText });
      }
    }
  }
}

async function deployProject(projectId, btn) {
  btn.disabled = true;
  btn.textContent = "Deploying...";
  try {
    const resp = await fetch("/api/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "deploy failed");
    btn.textContent = `Deployed → ${data.url}`;
    btn.onclick = () => window.open(data.url, "_blank");
  } catch (err) {
    btn.textContent = `Failed: ${err.message}`;
    btn.disabled = false;
  }
}

async function loadHistory() {
  const resp = await fetch("/api/history");
  const items = await resp.json();
  historyList.innerHTML = "";
  for (const item of items) {
    const el = document.createElement("div");
    el.className = "history-item";
    const date = new Date(item.created_at * 1000).toLocaleString();
    el.textContent = `${item.prompt.slice(0, 40)}${item.prompt.length > 40 ? "…" : ""}`;
    el.title = `${item.files.length} file(s) — ${date}`;
    historyList.appendChild(el);
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  streamChat(text);
});

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

modeToggle.addEventListener("click", (e) => {
  const btn = e.target.closest(".mode-btn");
  if (!btn) return;
  currentMode = btn.dataset.mode;
  modeToggle.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
});

document.getElementById("new-chat-btn").addEventListener("click", () => {
  conversation = [];
  chatWindow.innerHTML = `<div class="welcome"><h1>Void Cutting Slash</h1><p>New session started.</p></div>`;
});

document.getElementById("settings-btn").addEventListener("click", () => settingsModal.classList.remove("hidden"));
document.getElementById("close-settings").addEventListener("click", () => settingsModal.classList.add("hidden"));

document.getElementById("save-settings").addEventListener("click", async () => {
  const status = document.getElementById("settings-status");
  status.textContent = "Verifying...";
  status.className = "settings-status";
  const body = {};
  const nvidiaKey = document.getElementById("nvidia-key").value.trim();
  const vercelToken = document.getElementById("vercel-token").value.trim();
  const cloudUrl = document.getElementById("cloud-terminal-url").value.trim();
  if (nvidiaKey) body.nvidia_api_key = nvidiaKey;
  if (vercelToken) body.vercel_token = vercelToken;
  if (cloudUrl) body.cloud_terminal_url = cloudUrl;

  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "save failed");
    status.textContent = data.nvidia_key_verified
      ? `Saved. Key verified — ${data.nvidia_key_verified.model_count} models available.`
      : "Saved.";
    status.classList.add("ok");
    document.getElementById("nvidia-key").value = "";
    document.getElementById("vercel-token").value = "";
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("err");
  }
});

loadHistory();
