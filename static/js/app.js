const appEl = document.getElementById("app");
const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const historyList = document.getElementById("history-list");
const intentBadge = document.getElementById("intent-badge");
const modeToggle = document.getElementById("mode-toggle");
const settingsModal = document.getElementById("settings-modal");
const canvas = document.getElementById("canvas");
const canvasTitle = document.getElementById("canvas-title");
const canvasTabs = document.getElementById("canvas-tabs");
const canvasBody = document.getElementById("canvas-body");
const canvasOutput = document.getElementById("canvas-output");
const canvasOutputContent = document.getElementById("canvas-output-content");

let currentMode = "";
let conversation = [];
let currentProject = null; // { id, files, vercel_url }
let activeFilePath = null;
let terminalConnected = false;

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function clearWelcome() {
  const welcome = chatWindow.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function appendUserMessage(text) {
  clearWelcome();
  const row = document.createElement("div");
  row.className = "msg-row user";
  row.innerHTML = `<div class="msg"></div>`;
  row.querySelector(".msg").textContent = text;
  chatWindow.appendChild(row);
  scrollToBottom();
}

function appendAssistantMessage() {
  clearWelcome();
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.innerHTML = `<div class="msg"></div>`;
  chatWindow.appendChild(row);
  scrollToBottom();
  return row.querySelector(".msg");
}

function appendTierLog() {
  clearWelcome();
  const wrap = document.createElement("div");
  wrap.className = "tier-log";
  chatWindow.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

const TIER_LABELS = {
  generator: "Generator (Kimi-class)",
  auditor: "Auditor (GLM)",
  deep_reasoner: "Deep Reasoner (DeepSeek/Nemotron)",
  syntax_verifier: "Syntax Verifier",
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

function appendArtifactCard(id, fileCount) {
  const card = document.createElement("div");
  card.className = "artifact-card";
  card.innerHTML = `
    <div class="icon">◆</div>
    <div class="meta">
      <div class="name">Generated project</div>
      <div class="sub">${fileCount} file${fileCount === 1 ? "" : "s"} — click to open canvas</div>
    </div>
    <div class="open">Open →</div>
  `;
  card.addEventListener("click", () => openProjectInCanvas(id));
  chatWindow.appendChild(card);
  scrollToBottom();
}

function guessLang(path) {
  const ext = path.split(".").pop().toLowerCase();
  return { py: "python", js: "javascript", ts: "typescript", json: "json", html: "xml",
    css: "css", kt: "kotlin", sh: "bash", md: "markdown", yml: "yaml", yaml: "yaml" }[ext] || "plaintext";
}

function guessEntrypointAndLanguage(files) {
  const preferred = ["main.py", "app.py", "index.js", "server.js"];
  for (const p of preferred) if (p in files) return { entrypoint: p, language: p.endsWith(".py") ? "python" : "node" };
  const pyFile = Object.keys(files).find((f) => f.endsWith(".py"));
  if (pyFile) return { entrypoint: pyFile, language: "python" };
  const jsFile = Object.keys(files).find((f) => f.endsWith(".js"));
  if (jsFile) return { entrypoint: jsFile, language: "node" };
  return null;
}

async function openProjectInCanvas(id) {
  const resp = await fetch(`/api/history/${id}`);
  if (!resp.ok) return;
  const project = await resp.json();
  currentProject = project;
  activeFilePath = Object.keys(project.files)[0] || null;
  canvasTitle.textContent = project.prompt.slice(0, 60) + (project.prompt.length > 60 ? "…" : "");
  renderCanvasTabs();
  renderCanvasFile();
  canvasOutput.classList.add("hidden");
  appEl.classList.add("canvas-open");
  canvas.classList.remove("hidden");
}

function renderCanvasTabs() {
  canvasTabs.innerHTML = "";
  for (const path of Object.keys(currentProject.files)) {
    const tab = document.createElement("button");
    tab.className = "canvas-tab" + (path === activeFilePath ? " active" : "");
    tab.textContent = path;
    tab.addEventListener("click", () => {
      activeFilePath = path;
      renderCanvasTabs();
      renderCanvasFile();
    });
    canvasTabs.appendChild(tab);
  }
}

function renderCanvasFile() {
  const content = currentProject.files[activeFilePath] || "";
  const lang = guessLang(activeFilePath);
  canvasBody.innerHTML = `
    <div class="canvas-file-header">
      <span>${escapeHtml(activeFilePath)}</span>
      <button class="copy-btn" id="canvas-copy-btn">Copy</button>
    </div>
    <pre><code class="hljs language-${lang}" id="canvas-code"></code></pre>
  `;
  const codeEl = document.getElementById("canvas-code");
  codeEl.textContent = content;
  if (window.hljs) window.hljs.highlightElement(codeEl);

  document.getElementById("canvas-copy-btn").addEventListener("click", (e) => {
    navigator.clipboard.writeText(content);
    const btn = e.currentTarget;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 1500);
  });
}

document.getElementById("canvas-close-btn").addEventListener("click", () => {
  appEl.classList.remove("canvas-open");
  canvas.classList.add("hidden");
  currentProject = null;
});

document.getElementById("canvas-zip-btn").addEventListener("click", () => {
  if (!currentProject) return;
  window.open(`/api/history/${currentProject.id}/zip`, "_blank");
});

document.getElementById("canvas-run-btn").addEventListener("click", async () => {
  if (!currentProject) return;
  if (!terminalConnected) {
    showCanvasOutput("No Cloud Terminal connected. Open Settings and connect one to run real code.", true);
    return;
  }
  const guess = guessEntrypointAndLanguage(currentProject.files);
  if (!guess) {
    showCanvasOutput("Couldn't guess an entrypoint to run (no .py or .js file found).", true);
    return;
  }
  showCanvasOutput("Running on Cloud Terminal...");
  try {
    const resp = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: currentProject.id, entrypoint: guess.entrypoint, language: guess.language }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "execution failed");
    const lines = [
      `$ ${guess.language} ${guess.entrypoint}`,
      data.timed_out ? "[timed out]" : `[exit code ${data.exit_code}]`,
      "",
      data.stdout || "(no stdout)",
      data.stderr ? `\n--- stderr ---\n${data.stderr}` : "",
    ];
    showCanvasOutput(lines.join("\n"));
  } catch (err) {
    showCanvasOutput(`Error: ${err.message}`, true);
  }
});

document.getElementById("canvas-deploy-btn").addEventListener("click", async (e) => {
  if (!currentProject) return;
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Deploying...";
  try {
    const resp = await fetch("/api/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: currentProject.id }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "deploy failed");
    currentProject.vercel_url = data.url;
    btn.textContent = "Deployed ✓";
    showCanvasOutput(`Deployed: ${data.url}`);
  } catch (err) {
    btn.textContent = "Deploy to Vercel";
    showCanvasOutput(`Deploy failed: ${err.message}`, true);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("canvas-apk-btn").addEventListener("click", async (e) => {
  if (!currentProject) return;
  if (!terminalConnected) {
    showCanvasOutput("No Cloud Terminal connected. Open Settings and connect one to build a real APK.", true);
    return;
  }
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Building...";
  try {
    const resp = await fetch("/api/build-apk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: currentProject.id }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || "APK build failed");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "void-cutting-slash.apk";
    a.click();
    URL.revokeObjectURL(url);
    showCanvasOutput("APK built and downloaded.");
  } catch (err) {
    showCanvasOutput(`Build failed: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Build APK";
  }
});

document.getElementById("canvas-output-close").addEventListener("click", () => {
  canvasOutput.classList.add("hidden");
});

function showCanvasOutput(text, isError = false) {
  canvasOutput.classList.remove("hidden");
  canvasOutputContent.textContent = text;
  canvasOutputContent.style.color = isError ? "var(--danger)" : "var(--text-dim)";
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
    appendAssistantMessage().textContent = `Error: ${err.detail || "request failed"}`;
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
        scrollToBottom();
      } else if (kind === "tier") {
        if (!tierWrap) tierWrap = appendTierLog();
        upsertTierRow(tierWrap, data);
      } else if (kind === "result") {
        appendArtifactCard(data.id, Object.keys(data.files).length);
        openProjectInCanvas(data.id);
        loadHistory();
      } else if (kind === "error") {
        appendAssistantMessage().textContent = `Error: ${data.message}`;
      } else if (kind === "done") {
        if (assistantText) conversation.push({ role: "assistant", content: assistantText });
      }
    }
  }
}

async function loadHistory() {
  const resp = await fetch("/api/history");
  const items = await resp.json();
  historyList.innerHTML = "";
  for (const item of items) {
    const el = document.createElement("div");
    el.className = "history-item";
    el.textContent = item.prompt.slice(0, 42) + (item.prompt.length > 42 ? "…" : "");
    el.title = `${item.files.length} file(s)`;
    el.addEventListener("click", () => openProjectInCanvas(item.id));
    historyList.appendChild(el);
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  chatInput.style.height = "auto";
  streamChat(text);
});

chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
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
  intentBadge.textContent = "";
  chatWindow.innerHTML = `
    <div class="welcome">
      <div class="welcome-mark">◆</div>
      <h1>Void Cutting Slash</h1>
      <p>New session started.</p>
    </div>`;
});

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  appEl.classList.toggle("sidebar-collapsed");
});

document.getElementById("settings-btn").addEventListener("click", () => {
  settingsModal.classList.remove("hidden");
  loadSettingsIntoDrawer();
});
document.getElementById("close-settings").addEventListener("click", () => settingsModal.classList.add("hidden"));
document.getElementById("drawer-backdrop").addEventListener("click", () => settingsModal.classList.add("hidden"));

function setDot(el, state) {
  el.className = "status-dot status-dot--" + state; // "unset" | "ok" | "err"
}

async function loadSettingsIntoDrawer() {
  const resp = await fetch("/api/settings");
  const data = await resp.json();

  setDot(document.getElementById("nvidia-status"), data.nvidia_api_key ? "ok" : "unset");
  setDot(document.getElementById("vercel-status"), data.vercel_token ? "ok" : "unset");
  document.getElementById("cloud-terminal-url").value = data.cloud_terminal_url || "";

  renderModelGrid(data.models);
  refreshTerminalStatus();
  refreshSidebarStatus(!!data.nvidia_api_key);
}

function renderModelGrid(models) {
  const grid = document.getElementById("model-grid");
  grid.innerHTML = "";
  const labels = {
    fast_chat: "Fast Chat", generator: "Generator", auditor: "Auditor",
    deep_reasoner: "Deep Reasoner", syntax_verifier: "Syntax Verifier", safety_net: "Safety Net",
  };
  for (const [tier, model] of Object.entries(models || {})) {
    const row = document.createElement("div");
    row.className = "model-row";
    row.innerHTML = `<span class="tier">${labels[tier] || tier}</span><span class="model">${escapeHtml(model)}</span>`;
    grid.appendChild(row);
  }
}

async function refreshTerminalStatus() {
  const dot = document.getElementById("terminal-status");
  try {
    const resp = await fetch("/api/terminal/status");
    const data = await resp.json();
    terminalConnected = !!data.connected;
    setDot(dot, terminalConnected ? "ok" : "unset");
  } catch {
    terminalConnected = false;
    setDot(dot, "unset");
  }
}

function refreshSidebarStatus(nvidiaConfigured) {
  setDot(document.getElementById("settings-status-dot"), nvidiaConfigured ? "ok" : "unset");
}

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
  body.cloud_terminal_url = cloudUrl;

  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "save failed");

    const parts = [];
    if (data.nvidia_key_verified) parts.push(`NVIDIA key verified (${data.nvidia_key_verified.model_count} models).`);
    if (data.terminal_status) {
      parts.push(data.terminal_status.connected ? "Cloud Terminal connected." : `Cloud Terminal offline: ${data.terminal_status.error}`);
    }
    status.textContent = parts.join(" ") || "Saved.";
    status.classList.add(data.terminal_status && !data.terminal_status.connected ? "err" : "ok");

    document.getElementById("nvidia-key").value = "";
    document.getElementById("vercel-token").value = "";
    setDot(document.getElementById("nvidia-status"), data.nvidia_api_key ? "ok" : "unset");
    setDot(document.getElementById("vercel-status"), data.vercel_token ? "ok" : "unset");
    terminalConnected = !!(data.terminal_status && data.terminal_status.connected);
    setDot(document.getElementById("terminal-status"), terminalConnected ? "ok" : "unset");
    refreshSidebarStatus(!!data.nvidia_api_key);
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("err");
  }
});

loadHistory();
loadSettingsIntoDrawer();
