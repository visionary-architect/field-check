/**
 * Field Check GUI — Main entry point.
 *
 * Manages the three-screen flow: folder selection → scanning → report display.
 */

import { open, save } from "@tauri-apps/plugin-dialog";
import { ScannerIPC } from "./scanner-ipc.js";
import { renderReport } from "./report-renderer.js";

// --- State ---
let scanner = null;
let selectedPath = null;
let scanStartTime = null;
let elapsedTimer = null;
let lastReport = null;

// --- DOM Elements ---
const viewSelect = document.getElementById("view-select");
const viewProgress = document.getElementById("view-progress");
const viewReport = document.getElementById("view-report");

const btnSelectFolder = document.getElementById("btn-select-folder");
const btnStartScan = document.getElementById("btn-start-scan");
const selectedPathEl = document.getElementById("selected-path");
const btnCancel = document.getElementById("btn-cancel");
const phaseName = document.getElementById("phase-name");
const phaseProgress = document.getElementById("phase-progress");
const progressDetail = document.getElementById("progress-detail");
const phaseCounter = document.getElementById("phase-counter");
const elapsedTime = document.getElementById("elapsed-time");
const reportContent = document.getElementById("report-content");
const btnExportJson = document.getElementById("btn-export-json");
const btnExportHtml = document.getElementById("btn-export-html");
const btnNewScan = document.getElementById("btn-new-scan");

// --- View Management ---

function showView(view) {
  viewSelect.classList.remove("active");
  viewProgress.classList.remove("active");
  viewReport.classList.remove("active");
  view.classList.add("active");
}

// --- Scanner Lifecycle ---

async function initScanner() {
  scanner = new ScannerIPC();

  scanner.on("phase", (msg) => {
    phaseName.textContent = msg.name;
    phaseCounter.textContent = `Phase ${msg.index + 1} / ${msg.total}`;
    // Update overall progress bar based on phase
    const pct = ((msg.index + 1) / msg.total) * 100;
    phaseProgress.style.width = pct + "%";
  });

  scanner.on("progress", (msg) => {
    if (msg.total > 0) {
      progressDetail.textContent = `${msg.current} / ${msg.total}`;
    } else {
      progressDetail.textContent = `${msg.current} files found`;
    }
  });

  scanner.on("complete", (msg) => {
    stopTimer();
    lastReport = msg.report;
    reportContent.innerHTML = renderReport(msg.report);
    showView(viewReport);
  });

  scanner.on("error", (msg) => {
    stopTimer();
    reportContent.innerHTML = `<div class="card card-full">
      <h3>Error</h3>
      <p style="color: var(--danger)">${msg.message}</p>
    </div>`;
    showView(viewReport);
  });

  scanner.on("cancelled", () => {
    stopTimer();
    showView(viewSelect);
  });

  await scanner.spawn();
}

// --- Timer ---

function startTimer() {
  scanStartTime = Date.now();
  elapsedTimer = setInterval(() => {
    const secs = ((Date.now() - scanStartTime) / 1000).toFixed(0);
    elapsedTime.textContent = `${secs}s`;
  }, 500);
}

function stopTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// --- Event Handlers ---

btnSelectFolder.addEventListener("click", async () => {
  const folder = await open({ directory: true, multiple: false });
  if (folder) {
    selectedPath = folder;
    selectedPathEl.textContent = folder;
    btnStartScan.disabled = false;
  }
});

btnStartScan.addEventListener("click", async () => {
  if (!selectedPath || !scanner) return;

  // Reset progress UI
  phaseName.textContent = "Initializing";
  phaseProgress.style.width = "0%";
  progressDetail.textContent = "";
  phaseCounter.textContent = "Phase 0 / 12";
  elapsedTime.textContent = "0s";

  showView(viewProgress);
  startTimer();

  await scanner.scan(selectedPath);
});

btnCancel.addEventListener("click", async () => {
  if (scanner) {
    await scanner.cancel();
  }
});

btnNewScan.addEventListener("click", () => {
  lastReport = null;
  selectedPath = null;
  selectedPathEl.textContent = "";
  btnStartScan.disabled = true;
  showView(viewSelect);
});

btnExportJson.addEventListener("click", async () => {
  if (!lastReport) return;
  const path = await save({
    defaultPath: "field-check-report.json",
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (path) {
    const { writeTextFile } = await import("@tauri-apps/plugin-fs");
    await writeTextFile(path, JSON.stringify(lastReport, null, 2));
  }
});

btnExportHtml.addEventListener("click", async () => {
  if (!lastReport) return;
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
});

// --- Init ---

initScanner().catch((err) => {
  console.error("Failed to start scanner:", err);
  document.getElementById("app").innerHTML = `
    <div class="view active" style="text-align:center">
      <h2>Scanner failed to start</h2>
      <p style="color:var(--danger)">${err.message}</p>
      <p style="color:var(--text-muted);margin-top:1rem">
        Make sure the scanner binary is available in src-tauri/binaries/
      </p>
    </div>
  `;
});
