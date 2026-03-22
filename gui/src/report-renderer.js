/**
 * Report Renderer — Builds the scan report dashboard from JSON data.
 */

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Format bytes into a human-readable string.
 * @param {number} bytes
 * @returns {string}
 */
function formatSize(bytes) {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(1) + " " + units[i];
}

/**
 * Format seconds into a readable duration.
 * @param {number} seconds
 * @returns {string}
 */
function formatDuration(seconds) {
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

/**
 * Create an HTML card element.
 * @param {string} title - Card heading.
 * @param {string} content - Inner HTML.
 * @param {string} [extraClass] - Additional CSS class.
 * @returns {string}
 */
function card(title, content, extraClass = "") {
  return `<div class="card ${extraClass}">
    <h3>${title}</h3>
    ${content}
  </div>`;
}

/**
 * Render the summary cards (top-level stats).
 */
function renderSummary(summary) {
  const totalFiles = summary.total_files || 0;
  const totalSize = formatSize(summary.total_size || 0);
  const duration = formatDuration(summary.duration_seconds || 0);

  return `
    ${card("Total Files", `<div class="stat">${totalFiles.toLocaleString()}</div>`)}
    ${card("Total Size", `<div class="stat">${totalSize}</div>`)}
    ${card("Scan Duration", `<div class="stat">${duration}</div>`)}
  `;
}

/**
 * Render file type distribution table.
 */
function renderTypeDistribution(summary) {
  const types = summary.type_distribution || {};
  const entries = Object.entries(types).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return "";

  const totalFiles = summary.total_files || 1;
  const rows = entries
    .map(([type, count]) => {
      const pct = ((count / totalFiles) * 100).toFixed(1);
      return `<tr><td>${esc(type)}</td><td>${count.toLocaleString()} (${pct}%)</td></tr>`;
    })
    .join("");

  return card(
    "File Types",
    `<div class="table-scroll"><table>
      <tr><th>Type</th><th>Count</th></tr>
      ${rows}
    </table></div>`,
    "card-full"
  );
}

/**
 * Render duplicate detection results.
 */
function renderDuplicates(summary) {
  const dup = summary.duplicates;
  if (!dup) return "";

  const badge =
    dup.duplicate_percentage > 10
      ? '<span class="badge badge-danger">High</span>'
      : dup.duplicate_percentage > 5
        ? '<span class="badge badge-warn">Moderate</span>'
        : '<span class="badge badge-ok">Low</span>';

  return card(
    "Duplicates",
    `<div class="stat">${dup.duplicate_percentage?.toFixed(1) || 0}% ${badge}</div>
     <div class="stat-label">${(dup.duplicate_files || 0).toLocaleString()} duplicate files in ${(dup.duplicate_groups || 0).toLocaleString()} groups</div>
     <div class="stat-label">Wasted space: ${formatSize(dup.wasted_space || 0)}</div>`
  );
}

/**
 * Render corruption/health results.
 */
function renderCorruption(summary) {
  const cor = summary.corruption;
  if (!cor) return "";

  const total = (cor.ok || 0) + (cor.corrupt || 0) + (cor.encrypted || 0) + (cor.empty || 0);
  const healthPct = total > 0 ? ((cor.ok / total) * 100).toFixed(1) : "100.0";

  return card(
    "File Health",
    `<div class="stat">${healthPct}% <span class="badge badge-ok">Healthy</span></div>
     <div class="stat-label">Corrupt: ${cor.corrupt || 0} · Encrypted: ${cor.encrypted || 0} · Empty: ${cor.empty || 0}</div>`
  );
}

/**
 * Render PII risk indicators.
 */
function renderPII(summary) {
  const pii = summary.pii;
  if (!pii) return "";

  const badge =
    pii.files_with_pii > 0
      ? '<span class="badge badge-warn">Detected</span>'
      : '<span class="badge badge-ok">None</span>';

  let detail = `<div class="stat">${pii.files_with_pii || 0} files ${badge}</div>`;
  detail += `<div class="stat-label">Scanned: ${pii.total_scanned || 0} files</div>`;

  const types = pii.per_type_counts || {};
  if (Object.keys(types).length > 0) {
    const rows = Object.entries(types)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => `<tr><td>${esc(type)}</td><td>${count}</td></tr>`)
      .join("");
    detail += `<table><tr><th>Pattern</th><th>Files</th></tr>${rows}</table>`;
  }

  return card("PII Risk Indicators", detail);
}

/**
 * Render language distribution.
 */
function renderLanguage(summary) {
  const lang = summary.language;
  if (!lang || !lang.distribution) return "";

  const entries = Object.entries(lang.distribution).sort((a, b) => b[1] - a[1]);
  const rows = entries
    .map(([language, count]) => `<tr><td>${esc(language)}</td><td>${count}</td></tr>`)
    .join("");

  return card(
    "Languages",
    `<div class="table-scroll"><table>
      <tr><th>Language</th><th>Files</th></tr>
      ${rows}
    </table></div>`
  );
}

/**
 * Render encoding distribution.
 */
function renderEncoding(summary) {
  const enc = summary.encoding;
  if (!enc || !enc.distribution) return "";

  const entries = Object.entries(enc.distribution).sort((a, b) => b[1] - a[1]);
  const rows = entries
    .map(([encoding, count]) => `<tr><td>${esc(encoding)}</td><td>${count}</td></tr>`)
    .join("");

  return card(
    "Encodings",
    `<div class="table-scroll"><table>
      <tr><th>Encoding</th><th>Files</th></tr>
      ${rows}
    </table></div>`
  );
}

/**
 * Render near-duplicate detection results.
 */
function renderNearDuplicates(summary) {
  const nd = summary.near_duplicates;
  if (!nd) return "";

  return card(
    "Near-Duplicates",
    `<div class="stat">${nd.total_clusters || 0} clusters</div>
     <div class="stat-label">${nd.total_files_in_clusters || 0} files in near-duplicate groups</div>`
  );
}

/**
 * Render the full report from JSON data.
 * @param {object} report - The parsed JSON report from the sidecar.
 * @returns {string} HTML string for the report content area.
 */
export function renderReport(report) {
  const summary = report.summary || {};

  let html = renderSummary(summary);
  html += renderTypeDistribution(summary);
  html += renderDuplicates(summary);
  html += renderCorruption(summary);
  html += renderPII(summary);
  html += renderLanguage(summary);
  html += renderEncoding(summary);
  html += renderNearDuplicates(summary);

  html += `<div class="privacy-footer">
    Field Check v${esc(report.version || "0.1.0")} — All processing local. No data transmitted.
  </div>`;

  return html;
}
