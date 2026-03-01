import * as vscode from "vscode";

let channel: vscode.OutputChannel | undefined;

/** Create the GhostCode output channel */
export function createOutputChannel(): vscode.Disposable {
  channel = vscode.window.createOutputChannel("GhostCode");
  log("GhostCode extension activated");
  return channel;
}

/** Append a timestamped line to the output channel */
export function log(message: string): void {
  if (!channel) {
    return;
  }
  const ts = new Date().toISOString().slice(11, 23);
  channel.appendLine(`[${ts}] ${message}`);
}

/** Log an error and auto-show the output channel */
export function logError(message: string): void {
  log(`ERROR: ${message}`);
  showChannel();
}

/** Reveal the output channel */
export function showChannel(): void {
  channel?.show(true);
}

/** Dispose the output channel */
export function disposeOutputChannel(): void {
  channel?.dispose();
  channel = undefined;
}
