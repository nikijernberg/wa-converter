const INLINE_LIMIT = 750000;
const MAX_FILE = 40 * 1000 * 1000;

const importBox = document.querySelector("#import-box");
const jsonBox = document.querySelector("#json-box");
const status = document.querySelector("#status");
const reportWrap = document.querySelector("#report-wrap");
const report = document.querySelector("#report");
const downloadButton = document.querySelector("#download");
const fileInput = document.querySelector("#file");
const buttons = [...document.querySelectorAll("button")];

const state = { token: null, downloadName: "aura.json", busy: false };

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function setBusy(busy) {
  state.busy = busy;
  for (const button of buttons) {
    if (button.id === "download") {
      button.disabled = busy || !canDownload();
    } else {
      button.disabled = busy;
    }
  }
}

function canDownload() {
  const value = jsonBox.value.trim();
  return Boolean(state.token) || value.startsWith("{") || value.startsWith("[");
}

function errorText(data) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg || String(item)).join(" ");
  return "The request failed.";
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorText(data));
  return data;
}

function jsonPayload() {
  const value = jsonBox.value.trim();
  if (value.startsWith("{") || value.startsWith("[")) return { text: jsonBox.value };
  if (state.token) return { token: state.token };
  return null;
}

function apply(data, { keepReport = false } = {}) {
  state.token = data.token || null;
  state.downloadName = data.download_name || "aura.json";
  if (data.import_string) importBox.value = data.import_string;
  if (data.json_text) {
    jsonBox.value = data.json_text;
  } else if (data.token && data.size > INLINE_LIMIT) {
    const millions = (data.size / 1000000).toFixed(1);
    jsonBox.value = [
      `The aura ${data.label} is too large to show here (${millions} million characters).`,
      "",
      "Download the JSON, or press To Forever / Create import string.",
      "The converted copy is kept for 30 minutes.",
    ].join("\n");
  }
  if (data.report) {
    report.textContent = data.report;
    reportWrap.hidden = false;
  } else if (!keepReport) {
    reportWrap.hidden = true;
    report.textContent = "";
  }
  downloadButton.disabled = state.busy || !canDownload();
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

async function run(label, action) {
  if (state.busy) return;
  setBusy(true);
  setStatus(label);
  try {
    await action();
  } catch (error) {
    setStatus(error.message || "The request failed.", true);
  } finally {
    setBusy(false);
  }
}

document.querySelector("#paste").addEventListener("click", () => {
  run("Pasting…", async () => {
    const text = await navigator.clipboard.readText();
    if (!text.trim()) throw new Error("The clipboard is empty.");
    importBox.value = text;
    setStatus("Pasted.");
  });
});

document.querySelector("#open").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (!file) return;
  run(`Opening ${file.name}…`, async () => {
    if (file.size > MAX_FILE) throw new Error("That file is larger than 40 MB.");
    const text = await file.text();
    const compact = text.replace(/\s/g, "");
    if (compact.includes("!WA:")) {
      importBox.value = text.trim();
      setStatus(`Opened ${file.name}.`);
      return;
    }
    if (text.length <= INLINE_LIMIT) {
      jsonBox.value = text;
      state.token = null;
      downloadButton.disabled = !canDownload();
      setStatus(`Opened ${file.name}.`);
      return;
    }
    const data = await post("/api/open", { text });
    apply(data);
    setStatus(`Opened ${data.label}. The JSON is too large to show here.`);
  });
});

document.querySelector("#copy").addEventListener("click", () => {
  run("Copying…", async () => {
    const text = importBox.value.trim() ? importBox.value : jsonBox.value;
    if (!text.trim()) throw new Error("There is nothing to copy.");
    const copied = await copyText(text);
    if (!copied) throw new Error("Copy was blocked by the browser. Select the text and copy it yourself.");
    setStatus("Copied.");
  });
});

downloadButton.addEventListener("click", () => {
  const value = jsonBox.value.trim();
  if (value.startsWith("{") || value.startsWith("[")) {
    const blob = new Blob([jsonBox.value], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = state.downloadName || "aura.json";
    link.click();
    URL.revokeObjectURL(url);
    setStatus("JSON download started.");
    return;
  }
  if (!state.token) {
    setStatus("There is no JSON to download. Decode an export first.", true);
    return;
  }
  const link = document.createElement("a");
  link.href = `/api/files/${state.token}`;
  link.download = state.downloadName || "aura.json";
  link.click();
  setStatus("JSON download started.");
});

document.querySelector("#decode").addEventListener("click", () => {
  run("Decoding…", async () => {
    const text = importBox.value.trim();
    if (!text.includes("!WA:")) {
      throw new Error("No WeakAuras string found. Copy the whole export. It should start with !WA:2!");
    }
    const data = await post("/api/decode", { text: importBox.value });
    apply(data);
    setStatus(`Decoded ${data.label}.`);
  });
});

document.querySelector("#forever").addEventListener("click", () => {
  run("Converting to WoW: Forever…", async () => {
    const json = jsonPayload();
    const body = json || (importBox.value.includes("!WA:") ? { text: importBox.value } : null);
    if (!body) throw new Error("Paste a WeakAuras string or open a JSON file.");
    const data = await post("/api/forever", body);
    apply(data);
    const copied = data.import_string ? await copyText(data.import_string) : false;
    setStatus(copied ? `Converted ${data.label}. Import string copied.` : `Converted ${data.label}.`);
  });
});

document.querySelector("#encode").addEventListener("click", () => {
  run("Creating import string…", async () => {
    const body = jsonPayload();
    if (!body) throw new Error("There is no JSON to encode. Decode an export first.");
    const data = await post("/api/encode", body);
    apply(data, { keepReport: true });
    const copied = data.import_string ? await copyText(data.import_string) : false;
    setStatus(copied ? "Import string copied. Paste it into WeakAuras with Import." : "Import string created.");
  });
});
