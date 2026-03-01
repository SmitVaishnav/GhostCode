import * as vscode from "vscode";
import * as path from "path";
import { spawn } from "child_process";
import * as fs from "fs";
import { GhostMapData, HideResult, HideMultiResult, RevealResult, RiskReport } from "./types";
import { log } from "./outputChannel";

/**
 * Returns the bundled Python directory shipped inside the extension.
 * __dirname is the `out/` folder, so one level up is the extension root,
 * and `python/` sits next to `out/`.
 */
function getBundledPythonDir(): string {
  return path.join(__dirname, "..", "python");
}

/** Strip ANSI escape codes from CLI output */
function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

/**
 * In-memory resolved Python path. Set by auto-detect or Browse flow.
 * Takes priority over the user setting so we never need the user to
 * manually configure this on a standard install.
 */
let resolvedPythonPath: string | undefined;

/** Override the Python path for this session (auto-detect / browse result) */
export function setResolvedPythonPath(p: string): void {
  resolvedPythonPath = p;
  log(`Python resolved to: ${p}`);
}

/** Get the Python path: resolved > user setting > fallback "python3" */
function getPythonPath(): string {
  if (resolvedPythonPath) {
    return resolvedPythonPath;
  }
  return vscode.workspace.getConfiguration("ghostcode").get<string>("pythonPath", "python3");
}

/** Ordered list of Python candidates to try during auto-detection */
const PYTHON_CANDIDATES = [
  "python3",
  "python",
  "py",                          // Windows launcher
  "/usr/bin/python3",
  "/usr/local/bin/python3",
  "/opt/homebrew/bin/python3",   // macOS Apple Silicon Homebrew
  "/usr/bin/python",
];

/**
 * Try each candidate in order. Return the first one that successfully runs
 * `ghostcode.cli --version` with the bundled package, or null if none work.
 */
export function detectPython(): Promise<string | null> {
  const bundledDir = getBundledPythonDir();
  const existingPythonPath = process.env.PYTHONPATH ?? "";
  const pythonPath = existingPythonPath
    ? `${bundledDir}${path.delimiter}${existingPythonPath}`
    : bundledDir;

  const tryNext = (index: number): Promise<string | null> => {
    if (index >= PYTHON_CANDIDATES.length) {
      return Promise.resolve(null);
    }
    const candidate = PYTHON_CANDIDATES[index];
    return new Promise((resolve) => {
      log(`Auto-detect: trying ${candidate}`);
      let detectStderr = "";
      const child = spawn(candidate, ["-m", "ghostcode.cli", "--version"], {
        timeout: 5000,
        env: { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: "utf-8" },
      });
      child.stderr?.on("data", (data: Buffer) => { detectStderr += data.toString(); });
      child.on("close", (code) => {
        const isMsStore = /Microsoft Store/i.test(detectStderr) || /App execution aliases/i.test(detectStderr);
        if (code === 0 && !isMsStore) {
          log(`Auto-detect: found Python at "${candidate}"`);
          resolve(candidate);
        } else {
          resolve(tryNext(index + 1));
        }
      });
      child.on("error", () => {
        resolve(tryNext(index + 1));
      });
    });
  };

  return tryNext(0);
}

/** Get the workspace folder path, or fall back to the file's directory */
function getCwd(filePath?: string): string {
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (ws) {
    return ws;
  }
  if (filePath) {
    return require("path").dirname(filePath);
  }
  return process.cwd();
}

/** Run a CLI command and return stdout/stderr */
function runCli(args: string[], cwd: string): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const python = getPythonPath();
    const fullArgs = ["-m", "ghostcode.cli", ...args];
    log(`> ${python} ${fullArgs.join(" ")}`);

    // Prepend the bundled python/ dir to PYTHONPATH so the bundled ghostcode
    // package is always found, even if it is not installed system-wide.
    const bundledDir = getBundledPythonDir();
    const existingPythonPath = process.env.PYTHONPATH ?? "";
    const pythonPath = existingPythonPath
      ? `${bundledDir}${path.delimiter}${existingPythonPath}`
      : bundledDir;

    const child = spawn(python, fullArgs, {
      cwd,
      env: { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: "utf-8" },
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data: Buffer) => {
      const text = data.toString();
      stdout += text;
      for (const line of stripAnsi(text).split("\n").filter(Boolean)) {
        log(`[stdout] ${line}`);
      }
    });

    child.stderr.on("data", (data: Buffer) => {
      const text = data.toString();
      stderr += text;
      for (const line of stripAnsi(text).split("\n").filter(Boolean)) {
        log(`[stderr] ${line}`);
      }
    });

    child.on("close", (code) => {
      log(`CLI exited with code ${code}`);
      stdout = stripAnsi(stdout);
      stderr = stripAnsi(stderr);
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(stderr || stdout || `CLI exited with code ${code}`));
      }
    });

    child.on("error", (err) => {
      reject(new Error(`Failed to run GhostCode CLI: ${err.message}`));
    });
  });
}

/**
 * Run `ghostcode hide` on a file.
 * Parses the CLI output to extract ghost file and map file paths.
 */
export async function hide(
  filePath: string,
  level: number,
  functionName?: string
): Promise<HideResult> {
  const args = ["hide", filePath, "--level", String(level), "--no-copy", "--keep-comments"];
  if (functionName) {
    args.push("--function", functionName);
  }

  const cwd = getCwd(filePath);
  const { stdout } = await runCli(args, cwd);

  // Parse output lines to find file paths
  // CLI outputs lines like:
  //   Ghost output: ghost_test_config.py
  //   Map file: .ghostcode/maps/test_config_20260228_140742.json
  const ghostFileMatch = stdout.match(/Ghost output:\s*(.+)/i)
    ?? stdout.match(/Ghost file written\s*→\s*(.+)/i)
    ?? stdout.match(/ghost.*?written.*?:\s*(.+)/i);

  const mapFileMatch = stdout.match(/Map file:\s*(.+)/i)
    ?? stdout.match(/Map saved\s*→\s*(.+)/i)
    ?? stdout.match(/map.*?saved.*?:\s*(.+)/i);

  const path = require("path");

  const ghostFilePath = ghostFileMatch
    ? path.resolve(cwd, ghostFileMatch[1].trim())
    : "";
  const mapFilePath = mapFileMatch
    ? path.resolve(cwd, mapFileMatch[1].trim())
    : "";

  if (!ghostFilePath || !mapFilePath) {
    throw new Error(
      `Could not parse CLI output.\nstdout: ${stdout}\nExpected ghost file and map file paths.`
    );
  }

  // Parse risk report JSON if present
  let riskReport: RiskReport | undefined;
  const riskMatch = stdout.match(/RISK_REPORT_JSON:\s*(.+)/i);
  if (riskMatch) {
    try {
      riskReport = JSON.parse(riskMatch[1].trim()) as RiskReport;
      log(`Risk report parsed: exposure=${riskReport.exposure_level}, symbols=${riskReport.total_symbols}`);
    } catch {
      log("Failed to parse risk report JSON");
    }
  }

  return { ghostFilePath, mapFilePath, riskReport };
}

/**
 * Run `ghostcode reveal` on a ghost file using a map.
 */
export async function reveal(
  filePath: string,
  mapFilePath: string,
  sentFilePath?: string
): Promise<RevealResult> {
  const args = ["reveal", filePath, "--map-file", mapFilePath];
  if (sentFilePath) {
    args.push("--sent", sentFilePath);
  }
  const cwd = getCwd(filePath);
  const { stdout } = await runCli(args, cwd);

  // CLI outputs: "Output:    revealed_sample.py" or "Code output:    revealed_sample.py"
  const revealMatch = stdout.match(/(?:Code )?Output:\s*(.+)/i)
    ?? stdout.match(/Revealed.*?→\s*(.+)/i);

  const path = require("path");
  const revealedFilePath = revealMatch
    ? path.resolve(cwd, revealMatch[1].trim())
    : "";

  if (!revealedFilePath) {
    throw new Error(
      `Could not parse CLI output.\nstdout: ${stdout}\nExpected revealed file path.`
    );
  }

  return { revealedFilePath };
}

/**
 * Run `ghostcode hide` on multiple files at once.
 * The CLI shares a single GhostMap across all files.
 */
export async function hideMultiple(
  filePaths: string[],
  level: number
): Promise<HideMultiResult> {
  const args = ["hide", ...filePaths, "--level", String(level), "--no-copy", "--keep-comments"];

  const cwd = getCwd(filePaths[0]);
  const { stdout } = await runCli(args, cwd);

  const pathMod = require("path");

  // Multi-file output: "Files written  ghost_a.py, ghost_b.py"
  const multiMatch = stdout.match(/Files written\s+(.+)/i);
  let ghostFilePaths: string[];

  if (multiMatch) {
    ghostFilePaths = multiMatch[1]
      .split(",")
      .map((f: string) => pathMod.resolve(cwd, f.trim()));
  } else {
    // Fallback: single-file style "Ghost output: <path>"
    const singleMatch = stdout.match(/Ghost output:\s*(.+)/i)
      ?? stdout.match(/Ghost file written\s*→\s*(.+)/i)
      ?? stdout.match(/ghost.*?written.*?:\s*(.+)/i);
    if (singleMatch) {
      ghostFilePaths = [pathMod.resolve(cwd, singleMatch[1].trim())];
    } else {
      throw new Error(
        `Could not parse CLI output.\nstdout: ${stdout}\nExpected ghost file paths.`
      );
    }
  }

  // Map file: same format as single-file
  const mapFileMatch = stdout.match(/Map file:\s*(.+)/i)
    ?? stdout.match(/Map saved\s*→\s*(.+)/i)
    ?? stdout.match(/map.*?saved.*?:\s*(.+)/i);

  const mapFilePath = mapFileMatch
    ? pathMod.resolve(cwd, mapFileMatch[1].trim())
    : "";

  if (!mapFilePath) {
    throw new Error(
      `Could not parse CLI output.\nstdout: ${stdout}\nExpected map file path.`
    );
  }

  return { ghostFilePaths, mapFilePath };
}

/**
 * Run `ghostcode reveal` on multiple ghost files using a shared map.
 */
export async function revealMultiple(
  ghostFilePaths: string[],
  mapFilePath: string,
  sentFiles?: Map<string, string>
): Promise<RevealResult[]> {
  const results: RevealResult[] = [];
  for (const ghostFile of ghostFilePaths) {
    const sentFile = sentFiles?.get(ghostFile);
    const result = await reveal(ghostFile, mapFilePath, sentFile);
    results.push(result);
  }
  return results;
}

/**
 * Read a ghost map JSON file directly (no subprocess needed).
 */
export function readMap(mapFilePath: string): GhostMapData {
  const content = fs.readFileSync(mapFilePath, "utf-8");
  return JSON.parse(content) as GhostMapData;
}

/**
 * Turn a raw CLI error message into a user-friendly string.
 */
export function formatCliError(raw: string): string {
  if (/Microsoft Store/i.test(raw) || /App execution aliases/i.test(raw) || /was not found.*Microsoft/i.test(raw)) {
    return "Python is not installed. Please install Python from https://python.org/downloads, restart VS Code, then try again.";
  }
  if (/ModuleNotFoundError/i.test(raw)) {
    return "GhostCode CLI module not found. Run `pip install ghostcode` or check the ghostcode.pythonPath setting.";
  }
  if (/FileNotFoundError/i.test(raw)) {
    return "File not found — check that the file path is correct.";
  }
  if (/JSONDecodeError/i.test(raw) || (/JSON/i.test(raw) && /pars/i.test(raw))) {
    return "Ghost map appears corrupt. Try re-hiding the file to generate a fresh map.";
  }
  if (/ENOENT/i.test(raw) || /spawn.*error/i.test(raw)) {
    return "Python interpreter not found at the configured path. Check ghostcode.pythonPath in settings.";
  }
  if (/UnicodeDecodeError|UnicodeEncodeError/i.test(raw)) {
    return "File encoding error — the file may contain non-UTF-8 characters. Check Show Logs for details.";
  }
  // Unknown error — return a short version and let the output channel have the full traceback
  const firstLine = raw.split("\n").filter(Boolean).pop() ?? raw;
  return firstLine.length > 200 ? firstLine.substring(0, 200) + "…" : firstLine;
}

/**
 * Validate that the configured Python path can run ghostcode.
 * Returns true if validation passes, false otherwise.
 */
export function validatePython(): Promise<boolean> {
  return new Promise((resolve) => {
    const python = getPythonPath();
    log(`Validating Python: ${python} -m ghostcode.cli --version`);

    const bundledDir = getBundledPythonDir();
    const existingPythonPath = process.env.PYTHONPATH ?? "";
    const pythonPath = existingPythonPath
      ? `${bundledDir}${path.delimiter}${existingPythonPath}`
      : bundledDir;

    const child = spawn(python, ["-m", "ghostcode.cli", "--version"], {
      timeout: 5000,
      env: { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: "utf-8" },
    });

    let stdout = "";
    child.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });

    child.on("close", (code) => {
      if (code === 0) {
        log(`Python validation OK: ${stripAnsi(stdout).trim()}`);
        resolve(true);
      } else {
        log(`Python validation failed (exit code ${code})`);
        resolve(false);
      }
    });

    child.on("error", (err) => {
      log(`Python validation error: ${err.message}`);
      resolve(false);
    });
  });
}
