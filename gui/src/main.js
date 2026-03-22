/**
 * Field Check GUI — Main entry point.
 *
 * Manages the three-screen flow: folder selection → scanning → report display.
 */

import { getCurrentWindow } from "@tauri-apps/api/window";
import { open, save } from "@tauri-apps/plugin-dialog";
import { ScannerIPC } from "./scanner-ipc.js";
import { renderReport } from "./report-renderer.js";

/** Escape HTML to prevent XSS from sidecar error messages. */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

// --- State ---
let scanner = null;
let selectedPath = null;
let scanStartTime = null;
let elapsedTimer = null;
let lastReport = null;
let scanning = false;
let shuttingDown = false;

// --- DOM Elements (with null guards) ---
function $(id) {
  const el = document.getElementById(id);
  if (!el) console.error(`[gui] Missing DOM element: #${id}`);
  return el;
}

const viewSelect = $("view-select");
const viewProgress = $("view-progress");
const viewReport = $("view-report");

const btnSelectFolder = $("btn-select-folder");
const btnStartScan = $("btn-start-scan");
const selectedPathEl = $("selected-path");
const btnCancel = $("btn-cancel");
const phaseName = $("phase-name");
const phaseProgress = $("phase-progress");
const progressDetail = $("progress-detail");
const phaseCounter = $("phase-counter");
const elapsedTime = $("elapsed-time");
const reportContent = $("report-content");
const btnExportJson = $("btn-export-json");
const btnExportHtml = $("btn-export-html");
const btnNewScan = $("btn-new-scan");

// --- View Management ---

function showView(view) {
  if (!view) return;
  viewSelect?.classList.remove("active");
  viewProgress?.classList.remove("active");
  viewReport?.classList.remove("active");
  view.classList.add("active");
}

/** Called when a scan finishes (complete, error, cancelled, or crash). */
function onScanEnd() {
  scanning = false;
  stopTimer();
}

// --- Scanner Lifecycle ---

/** Wire up all event listeners on the scanner instance. */
function attachScannerListeners() {
  scanner.on("phase", (msg) => {
    if (phaseName) phaseName.textContent = msg.name;
    if (phaseCounter)
      phaseCounter.textContent = `Phase ${msg.index + 1} / ${msg.total}`;
    if (phaseProgress) {
      const pct = msg.total > 0 ? ((msg.index + 1) / msg.total) * 100 : 0;
      phaseProgress.style.width = pct + "%";
    }
  });

  scanner.on("progress", (msg) => {
    if (!progressDetail) return;
    if (msg.total > 0) {
      progressDetail.textContent = `${msg.current} / ${msg.total}`;
    } else {
      progressDetail.textContent = `${msg.current} files found`;
    }
  });

  scanner.on("complete", (msg) => {
    onScanEnd();
    if (phaseProgress) phaseProgress.style.width = "100%";
    lastReport = msg.report;
    if (reportContent) reportContent.innerHTML = renderReport(msg.report);
    showView(viewReport);
  });

  scanner.on("error", (msg) => {
    onScanEnd();
    if (reportContent) {
      reportContent.innerHTML = `<div class="card card-full">
        <h3>Error</h3>
        <p style="color: var(--danger)">${escapeHtml(msg.message)}</p>
      </div>`;
    }
    showView(viewReport);
  });

  scanner.on("cancelled", () => {
    onScanEnd();
    showView(viewSelect);
  });

  scanner.on("close", () => {
    // Sidecar crashed or exited unexpectedly during scan
    if (scanning) {
      onScanEnd();
      if (reportContent) {
        reportContent.innerHTML = `<div class="card card-full">
          <h3>Scanner Crashed</h3>
          <p style="color: var(--danger)">The scanner process exited unexpectedly.</p>
          <p style="color: var(--text-muted)">Try starting a new scan.</p>
        </div>`;
      }
      showView(viewReport);
    }
    // Auto-restart sidecar so "New Scan" works after a crash
    if (!shuttingDown) restartScanner();
  });
}

/** Restart the sidecar after a crash. */
async function restartScanner() {
  try {
    scanner = new ScannerIPC();
    await scanner.spawn();
    attachScannerListeners();
  } catch (err) {
    console.error("[gui] Failed to restart scanner:", err);
    scanner = null;
  }
}

async function initScanner() {
  scanner = new ScannerIPC();

  // Spawn first, THEN register listeners — spawn() clears listeners
  await scanner.spawn();
  attachScannerListeners();
}

// --- Timer ---

function startTimer() {
  stopTimer(); // Prevent interval leak on double-call
  scanStartTime = Date.now();
  elapsedTimer = setInterval(() => {
    const secs = ((Date.now() - scanStartTime) / 1000).toFixed(0);
    if (elapsedTime) elapsedTime.textContent = `${secs}s`;
  }, 500);
}

function stopTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// --- Event Handlers ---

btnSelectFolder?.addEventListener("click", async () => {
  const folder = await open({ directory: true, multiple: false });
  if (folder) {
    selectedPath = folder;
    if (selectedPathEl) selectedPathEl.textContent = folder;
    if (btnStartScan) btnStartScan.disabled = false;
  }
});

btnStartScan?.addEventListener("click", async () => {
  if (!selectedPath || !scanner || scanning) return;
  scanning = true;

  // Reset progress UI
  if (phaseName) phaseName.textContent = "Initializing";
  if (phaseProgress) phaseProgress.style.width = "0%";
  if (progressDetail) progressDetail.textContent = "";
  if (phaseCounter) phaseCounter.textContent = "Phase 0 / 12";
  if (elapsedTime) elapsedTime.textContent = "0s";

  showView(viewProgress);
  startTimer();

  try {
    await scanner.scan(selectedPath);
  } catch (err) {
    onScanEnd();
    if (reportContent) {
      reportContent.innerHTML = `<div class="card card-full">
        <h3>Error</h3>
        <p style="color: var(--danger)">${escapeHtml(err.message)}</p>
      </div>`;
    }
    showView(viewReport);
  }
});

btnCancel?.addEventListener("click", async () => {
  if (scanner) {
    await scanner.cancel();
  }
});

btnNewScan?.addEventListener("click", () => {
  lastReport = null;
  selectedPath = null;
  if (selectedPathEl) selectedPathEl.textContent = "";
  if (btnStartScan) btnStartScan.disabled = true;
  // Reset progress UI to avoid stale data flash on next scan
  if (phaseName) phaseName.textContent = "Initializing";
  if (phaseProgress) phaseProgress.style.width = "0%";
  if (progressDetail) progressDetail.textContent = "";
  if (phaseCounter) phaseCounter.textContent = "";
  if (elapsedTime) elapsedTime.textContent = "0s";
  showView(viewSelect);
});

btnExportJson?.addEventListener("click", async () => {
  if (!lastReport) return;
  try {
    const path = await save({
      defaultPath: "field-check-report.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (path) {
      const { writeTextFile } = await import("@tauri-apps/plugin-fs");
      await writeTextFile(path, JSON.stringify(lastReport, null, 2));
    }
  } catch (err) {
    console.error("Export failed:", err);
    reportContent?.querySelector(".card-full")?.insertAdjacentHTML(
      "beforeend",
      `<p style="color:var(--danger);margin-top:1rem">Export failed: ${escapeHtml(err.message)}</p>`
    );
  }
});

btnExportHtml?.addEventListener("click", async () => {
  if (!lastReport) return;
  try {
    const path = await save({
      defaultPath: "field-check-report.html",
      filters: [{ name: "HTML", extensions: ["html"] }],
    });
    if (path) {
      const html = `<!DOCTYPE html>
<html><head><title>Field Check Report</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;}</style>
</head><body>${renderReport(lastReport)}</body></html>`;
      const { writeTextFile } = await import("@tauri-apps/plugin-fs");
      await writeTextFile(path, html);
    }
  } catch (err) {
    console.error("Export failed:", err);
    reportContent?.querySelector(".card-full")?.insertAdjacentHTML(
      "beforeend",
      `<p style="color:var(--danger);margin-top:1rem">Export failed: ${escapeHtml(err.message)}</p>`
    );
  }
});

// --- Window Close ---

getCurrentWindow()
  .onCloseRequested(async () => {
    shuttingDown = true;
    if (scanner) {
      await scanner.shutdown();
    }
  })
  .catch(() => {
    // May fail in dev mode — non-critical
  });

// --- Init ---

initScanner().catch((err) => {
  console.error("Failed to start scanner:", err);
  // Show error in the select view instead of destroying the entire DOM
  if (viewSelect) {
    viewSelect.innerHTML = `
      <div style="text-align:center">
        <h2>Scanner failed to start</h2>
        <p style="color:var(--danger)">${escapeHtml(err.message)}</p>
        <p style="color:var(--text-muted);margin-top:1rem">
          Make sure the scanner binary is available in src-tauri/binaries/
        </p>
      </div>
    `;
  }
});
