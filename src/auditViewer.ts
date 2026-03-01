import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

interface AuditEntry {
  timestamp: string;
  action: "hide" | "reveal";
  user?: string;
  hostname?: string;
  // Hide fields
  source_files?: string[];
  scrub_level?: number;
  function_isolated?: string | null;
  symbols_scrubbed?: number;
  literals_scrubbed?: number;
  literals_flagged?: number;
  literals_kept?: number;
  comments_stripped?: number;
  warnings?: string[];
  warning_count?: number;
  ghost_output_hash?: string;
  map_hash?: string;
  // Reveal fields
  input_file?: string;
  map_used?: string;
  mode?: string;
  symbols_restored?: number;
  new_symbols_detected?: number;
  new_symbols?: string[];
  new_dependencies?: string[];
  annotations?: number;
  confidence?: string;
  confidence_score?: number;
  output_hash?: string;
}

let currentPanel: vscode.WebviewPanel | undefined;

/**
 * Read all audit log entries from ~/.ghostcode/audit/
 */
function readAuditEntries(limit: number = 100): AuditEntry[] {
  const auditDir = path.join(os.homedir(), ".ghostcode", "audit");
  if (!fs.existsSync(auditDir)) {
    return [];
  }

  const logFiles = fs.readdirSync(auditDir)
    .filter((f) => f.endsWith(".jsonl"))
    .sort()
    .reverse(); // newest first

  const entries: AuditEntry[] = [];

  for (const logFile of logFiles) {
    const filePath = path.join(auditDir, logFile);
    const lines = fs.readFileSync(filePath, "utf-8").split("\n").filter(Boolean);

    for (const line of lines.reverse()) {
      try {
        entries.push(JSON.parse(line) as AuditEntry);
      } catch {
        // skip malformed lines
      }
      if (entries.length >= limit) {
        break;
      }
    }
    if (entries.length >= limit) {
      break;
    }
  }

  return entries;
}

/**
 * Format a timestamp for display
 */
function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    return `${date} ${time}`;
  } catch {
    return iso;
  }
}

/**
 * Build the webview HTML content
 */
function getWebviewContent(entries: AuditEntry[]): string {
  const rows = entries.map((e) => {
    const isHide = e.action === "hide";
    const actionBadge = isHide
      ? `<span class="badge badge-hide">HIDE</span>`
      : `<span class="badge badge-reveal">REVEAL</span>`;

    let files = "";
    if (isHide && e.source_files) {
      files = e.source_files.map((f) => path.basename(f)).join(", ");
    } else if (!isHide && e.input_file) {
      files = path.basename(e.input_file);
    }

    let details = "";
    if (isHide) {
      const parts: string[] = [];
      if (e.scrub_level) { parts.push(`Level ${e.scrub_level}`); }
      if (e.symbols_scrubbed) { parts.push(`${e.symbols_scrubbed} symbols`); }
      if (e.literals_scrubbed) { parts.push(`${e.literals_scrubbed} literals scrubbed`); }
      if (e.literals_flagged) { parts.push(`${e.literals_flagged} flagged`); }
      if (e.comments_stripped) { parts.push(`${e.comments_stripped} comments`); }
      if (e.function_isolated) { parts.push(`fn: ${e.function_isolated}`); }
      details = parts.join(" &middot; ");
    } else {
      const parts: string[] = [];
      if (e.symbols_restored) { parts.push(`${e.symbols_restored} restored`); }
      if (e.new_symbols_detected) { parts.push(`${e.new_symbols_detected} new symbols`); }
      if (e.confidence) {
        const confClass = e.confidence === "HIGH" ? "conf-high" : e.confidence === "MEDIUM" ? "conf-med" : "conf-low";
        parts.push(`<span class="${confClass}">${e.confidence}</span> confidence`);
      }
      if (e.annotations) { parts.push(`${e.annotations} annotations`); }
      details = parts.join(" &middot; ");
    }

    const warnings = (e.warning_count && e.warning_count > 0)
      ? `<span class="warning-badge">${e.warning_count} warning${e.warning_count > 1 ? "s" : ""}</span>`
      : "";

    const hash = isHide
      ? (e.ghost_output_hash ? e.ghost_output_hash.substring(0, 8) : "")
      : (e.output_hash ? e.output_hash.substring(0, 8) : "");

    return `
      <tr class="${isHide ? "row-hide" : "row-reveal"}">
        <td class="col-time">${formatTime(e.timestamp)}</td>
        <td class="col-action">${actionBadge}</td>
        <td class="col-files" title="${files}">${files}</td>
        <td class="col-details">${details} ${warnings}</td>
        <td class="col-hash" title="${isHide ? e.ghost_output_hash : e.output_hash}"><code>${hash}</code></td>
      </tr>
    `;
  }).join("\n");

  const totalHides = entries.filter((e) => e.action === "hide").length;
  const totalReveals = entries.filter((e) => e.action === "reveal").length;
  const totalSymbols = entries.reduce((sum, e) => sum + (e.symbols_scrubbed || e.symbols_restored || 0), 0);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  :root {
    --bg: #0e1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent-blue: #58a6ff;
    --accent-green: #3fb950;
    --accent-purple: #bc8cff;
    --accent-yellow: #d29922;
    --accent-red: #f85149;
    --hide-bg: rgba(63, 185, 80, 0.06);
    --reveal-bg: rgba(88, 166, 255, 0.06);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
    line-height: 1.5;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }

  .header h1 {
    font-size: 20px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .header h1 .icon {
    font-size: 24px;
  }

  .stats {
    display: flex;
    gap: 24px;
  }

  .stat {
    text-align: center;
  }

  .stat-value {
    font-size: 24px;
    font-weight: 700;
    line-height: 1;
  }

  .stat-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }

  .stat-hide .stat-value { color: var(--accent-green); }
  .stat-reveal .stat-value { color: var(--accent-blue); }
  .stat-symbols .stat-value { color: var(--accent-purple); }

  .filter-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
  }

  .filter-btn {
    padding: 5px 14px;
    border-radius: 16px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-muted);
    cursor: pointer;
    font-size: 12px;
    font-weight: 500;
    transition: all 0.15s ease;
  }

  .filter-btn:hover { border-color: var(--accent-blue); color: var(--text); }
  .filter-btn.active { background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  thead th {
    text-align: left;
    padding: 10px 12px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    position: sticky;
    top: 0;
    background: var(--bg);
  }

  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background 0.1s ease;
  }

  tbody tr:hover { background: var(--surface); }
  .row-hide { background: var(--hide-bg); }
  .row-reveal { background: var(--reveal-bg); }

  td {
    padding: 10px 12px;
    vertical-align: middle;
  }

  .col-time {
    color: var(--text-muted);
    white-space: nowrap;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  .col-action { width: 80px; }

  .col-files {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }

  .col-details { color: var(--text-muted); }
  .col-hash code {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 11px;
    color: var(--text-muted);
    background: var(--surface);
    padding: 2px 6px;
    border-radius: 4px;
  }

  .badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }

  .badge-hide {
    background: rgba(63, 185, 80, 0.15);
    color: var(--accent-green);
    border: 1px solid rgba(63, 185, 80, 0.3);
  }

  .badge-reveal {
    background: rgba(88, 166, 255, 0.15);
    color: var(--accent-blue);
    border: 1px solid rgba(88, 166, 255, 0.3);
  }

  .warning-badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    background: rgba(210, 153, 34, 0.15);
    color: var(--accent-yellow);
    border: 1px solid rgba(210, 153, 34, 0.3);
    margin-left: 4px;
  }

  .conf-high { color: var(--accent-green); font-weight: 600; }
  .conf-med { color: var(--accent-yellow); font-weight: 600; }
  .conf-low { color: var(--accent-red); font-weight: 600; }

  .empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
  }

  .empty-state .icon { font-size: 48px; margin-bottom: 16px; }
  .empty-state h2 { font-size: 18px; color: var(--text); margin-bottom: 8px; }
  .empty-state p { font-size: 14px; }
</style>
</head>
<body>

${entries.length === 0 ? `
  <div class="empty-state">
    <div class="icon">📋</div>
    <h2>No audit logs yet</h2>
    <p>Audit entries will appear here after you hide or reveal files.</p>
  </div>
` : `
  <div class="header">
    <h1><span class="icon">🛡️</span> GhostCode Audit Log</h1>
    <div class="stats">
      <div class="stat stat-hide">
        <div class="stat-value">${totalHides}</div>
        <div class="stat-label">Hides</div>
      </div>
      <div class="stat stat-reveal">
        <div class="stat-value">${totalReveals}</div>
        <div class="stat-label">Reveals</div>
      </div>
      <div class="stat stat-symbols">
        <div class="stat-value">${totalSymbols}</div>
        <div class="stat-label">Symbols</div>
      </div>
    </div>
  </div>

  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterRows('all')">All</button>
    <button class="filter-btn" onclick="filterRows('hide')">Hides</button>
    <button class="filter-btn" onclick="filterRows('reveal')">Reveals</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Action</th>
        <th>File(s)</th>
        <th>Details</th>
        <th>Hash</th>
      </tr>
    </thead>
    <tbody id="logBody">
      ${rows}
    </tbody>
  </table>
`}

<script>
  function filterRows(type) {
    const rows = document.querySelectorAll('#logBody tr');
    const buttons = document.querySelectorAll('.filter-btn');

    buttons.forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');

    rows.forEach(row => {
      if (type === 'all') {
        row.style.display = '';
      } else if (type === 'hide') {
        row.style.display = row.classList.contains('row-hide') ? '' : 'none';
      } else if (type === 'reveal') {
        row.style.display = row.classList.contains('row-reveal') ? '' : 'none';
      }
    });
  }
</script>

</body>
</html>`;
}

/**
 * Open the audit log webview panel
 */
export function showAuditLog(context: vscode.ExtensionContext): void {
  if (currentPanel) {
    currentPanel.reveal(vscode.ViewColumn.One);
    // Refresh data
    const entries = readAuditEntries();
    currentPanel.webview.html = getWebviewContent(entries);
    return;
  }

  currentPanel = vscode.window.createWebviewPanel(
    "ghostcodeAudit",
    "GhostCode Audit Log",
    vscode.ViewColumn.One,
    { enableScripts: true }
  );

  const entries = readAuditEntries();
  currentPanel.webview.html = getWebviewContent(entries);

  currentPanel.onDidDispose(() => {
    currentPanel = undefined;
  }, null, context.subscriptions);
}
