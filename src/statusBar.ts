import * as vscode from "vscode";
import { GhostMapData } from "./types";

let statusBarItem: vscode.StatusBarItem | undefined;

/** Create the GhostCode status bar item */
export function createStatusBar(): vscode.StatusBarItem {
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBarItem.command = "ghostcode.showMap";
  statusBarItem.tooltip = "Click to inspect Ghost Map";
  statusBarItem.hide();
  return statusBarItem;
}

/** Update status bar with current map info */
export function updateStatusBar(mapData: GhostMapData | undefined): void {
  if (!statusBarItem) {
    return;
  }
  if (!mapData) {
    statusBarItem.hide();
    return;
  }
  const count = Object.keys(mapData.symbols).length;
  const fileCount = mapData.files.length;
  statusBarItem.text = fileCount > 1
    ? `$(eye-closed) Ghost: ${count} symbols across ${fileCount} files`
    : `$(eye-closed) Ghost: ${count} symbols`;
  statusBarItem.show();
}

/** Dispose the status bar item */
export function disposeStatusBar(): void {
  statusBarItem?.dispose();
  statusBarItem = undefined;
}
