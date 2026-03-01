import * as vscode from "vscode";
import { GhostMapData, GHOST_TOKEN_REGEX, TOKEN_PREFIXES } from "./types";

/** One decoration type per token prefix */
const decorationTypes: Map<string, vscode.TextEditorDecorationType> = new Map();

/** Initialize decoration types for each prefix */
function ensureDecorationTypes(): void {
  if (decorationTypes.size > 0) {
    return;
  }
  for (const [prefix, meta] of Object.entries(TOKEN_PREFIXES)) {
    decorationTypes.set(
      prefix,
      vscode.window.createTextEditorDecorationType({
        backgroundColor: meta.color,
        borderRadius: "3px",
      })
    );
  }
}

/**
 * Apply ghost token decorations to the active editor.
 * Highlights tokens with color-coded backgrounds and hover tooltips.
 */
export function applyDecorations(
  editor: vscode.TextEditor,
  mapData: GhostMapData | undefined
): void {
  ensureDecorationTypes();

  // Collect ranges grouped by prefix
  const rangesByPrefix: Map<string, vscode.DecorationOptions[]> = new Map();
  for (const prefix of Object.keys(TOKEN_PREFIXES)) {
    rangesByPrefix.set(prefix, []);
  }

  const text = editor.document.getText();
  let match: RegExpExecArray | null;

  // Reset lastIndex for global regex
  const regex = new RegExp(GHOST_TOKEN_REGEX.source, "g");

  while ((match = regex.exec(text)) !== null) {
    const token = match[0];
    const prefix = token.substring(0, 2);
    const ranges = rangesByPrefix.get(prefix);
    if (!ranges) {
      continue;
    }

    const startPos = editor.document.positionAt(match.index);
    const endPos = editor.document.positionAt(match.index + token.length);
    const range = new vscode.Range(startPos, endPos);

    // Build hover tooltip
    let hoverMessage: string;
    if (mapData && mapData.symbols[token]) {
      const entry = mapData.symbols[token];
      hoverMessage = `**${token}** → \`${entry.original}\`\n\n*Kind:* ${entry.kind}`;
      if (entry.scope) {
        hoverMessage += `\n*Scope:* ${entry.scope}`;
      }
    } else {
      const meta = TOKEN_PREFIXES[prefix];
      hoverMessage = `**${token}** (${meta?.label ?? "Unknown"})`;
    }

    ranges.push({
      range,
      hoverMessage: new vscode.MarkdownString(hoverMessage),
    });
  }

  // Apply decorations
  for (const [prefix, decType] of decorationTypes) {
    const ranges = rangesByPrefix.get(prefix) ?? [];
    editor.setDecorations(decType, ranges);
  }
}

/** Clear all ghost decorations from an editor */
export function clearDecorations(editor: vscode.TextEditor): void {
  for (const decType of decorationTypes.values()) {
    editor.setDecorations(decType, []);
  }
}

/** Dispose all decoration types (for extension deactivation) */
export function disposeDecorations(): void {
  for (const decType of decorationTypes.values()) {
    decType.dispose();
  }
  decorationTypes.clear();
}
