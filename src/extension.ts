import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import * as ghostRunner from "./ghostRunner";
import { GhostMapTreeProvider } from "./mapViewer";
import { applyDecorations, clearDecorations, disposeDecorations } from "./decorations";
import { createStatusBar, updateStatusBar, disposeStatusBar } from "./statusBar";
import { createOutputChannel, log, logError, showChannel, disposeOutputChannel } from "./outputChannel";
import { GhostMapData, PRIVACY_LEVELS } from "./types";
import { showAuditLog } from "./auditViewer";

let currentMapData: GhostMapData | undefined;
let treeProvider: GhostMapTreeProvider;

/** Maps ghost file path → map file path so reveal is one click */
const ghostToMap: Map<string, string> = new Map();

/** Maps ghost file path → original ghost file path for AI-change annotation */
const ghostToSent: Map<string, string> = new Map();

/** Maps ghost file path → snapshot of original file content (for accurate diff) */
const ghostToOriginalContent: Map<string, { content: string; fileName: string }> = new Map();

/** Maps map file path → set of ghost file paths (for multi-file reveal) */
const mapToGhosts: Map<string, Set<string>> = new Map();

export function activate(context: vscode.ExtensionContext) {
  // --- Output Channel ---
  context.subscriptions.push(createOutputChannel());

  // --- Welcome view context ---
  vscode.commands.executeCommand("setContext", "ghostcode.mapLoaded", false);

  // --- Status Bar ---
  const statusBar = createStatusBar();
  context.subscriptions.push(statusBar);

  // --- Tree View ---
  treeProvider = new GhostMapTreeProvider();
  const treeView = vscode.window.createTreeView("ghostcodeMap", {
    treeDataProvider: treeProvider,
  });
  context.subscriptions.push(treeView);

  // --- Python Auto-Detect (non-blocking) ---
  ghostRunner.validatePython().then(async (ok) => {
    if (ok) {
      log("Python validation OK with current setting");
      return;
    }

    // Current setting didn't work — try to auto-detect
    log("Python validation failed — running auto-detect");
    const found = await ghostRunner.detectPython();

    if (found) {
      ghostRunner.setResolvedPythonPath(found);
      log(`Auto-detected Python: ${found}`);
      return;
    }

    // Nothing found — show guided prompt
    log("Python not found anywhere — showing setup prompt");
    const choice = await vscode.window.showWarningMessage(
      "GhostCode: Python not found. GhostCode needs Python 3 to run.",
      "Browse for Python",
      "Install Python",
      "Enter Path Manually"
    );

    if (choice === "Browse for Python") {
      const uris = await vscode.window.showOpenDialog({
        canSelectMany: false,
        canSelectFolders: false,
        title: "Select your Python 3 executable",
        filters: process.platform === "win32"
          ? { "Executable": ["exe"] }
          : { "All files": ["*"] },
      });
      if (uris && uris.length > 0) {
        const selectedPath = uris[0].fsPath;
        await vscode.workspace
          .getConfiguration("ghostcode")
          .update("pythonPath", selectedPath, vscode.ConfigurationTarget.Global);
        ghostRunner.setResolvedPythonPath(selectedPath);
        vscode.window.showInformationMessage(
          `GhostCode: Python set to "${selectedPath}"`
        );
      }
    } else if (choice === "Install Python") {
      vscode.env.openExternal(vscode.Uri.parse("https://www.python.org/downloads/"));
    } else if (choice === "Enter Path Manually") {
      const entered = await vscode.window.showInputBox({
        prompt: "Enter the full path to your Python 3 executable",
        placeHolder: process.platform === "win32"
          ? "e.g. C:\\Python311\\python.exe"
          : "e.g. /usr/local/bin/python3",
        ignoreFocusOut: true,
      });
      if (entered && entered.trim()) {
        const trimmed = entered.trim();
        await vscode.workspace
          .getConfiguration("ghostcode")
          .update("pythonPath", trimmed, vscode.ConfigurationTarget.Global);
        ghostRunner.setResolvedPythonPath(trimmed);
        vscode.window.showInformationMessage(
          `GhostCode: Python set to "${trimmed}"`
        );
      }
    }
  });

  // --- Commands ---

  // Hide File — two clicks: trigger + pick level
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.hideFile", async (uri?: vscode.Uri) => {
      const filePath = uri?.fsPath ?? vscode.window.activeTextEditor?.document.uri.fsPath;
      if (!filePath) {
        vscode.window.showWarningMessage("GhostCode: No file selected.");
        return;
      }

      // Pick privacy level
      const picked = await vscode.window.showQuickPick(
        PRIVACY_LEVELS.map((p) => ({
          label: p.label,
          description: p.description,
          level: p.level,
        })),
        { placeHolder: "Select privacy level" }
      );
      if (!picked) {
        return;
      }

      // Optional function name for Level 3+
      let functionName: string | undefined;
      if (picked.level >= 3) {
        functionName =
          (await vscode.window.showInputBox({
            prompt: "Function to isolate (leave blank for full file)",
            placeHolder: "e.g. calculate_total",
          })) || undefined;
      }

      const fileName = path.basename(filePath);

      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "GhostCode",
            cancellable: false,
          },
          async (progress) => {
            progress.report({ message: `Analyzing "${fileName}"...`, increment: 0 });

            progress.report({ message: `Hiding at Level ${picked.level}...`, increment: 30 });
            const result = await ghostRunner.hide(filePath, picked.level, functionName);

            // Remember the ghost→map association for one-click reveal
            ghostToMap.set(result.ghostFilePath, result.mapFilePath);
            // Store the original ghost file path for AI-change annotation
            ghostToSent.set(result.ghostFilePath, result.ghostFilePath);
            // Snapshot original file content for diff view later
            try {
              const originalContent = fs.readFileSync(filePath, "utf-8");
              ghostToOriginalContent.set(result.ghostFilePath, {
                content: originalContent,
                fileName: path.basename(filePath),
              });
            } catch {
              // Non-critical — diff just won't be available
            }

            progress.report({ message: "Loading ghost map...", increment: 30 });
            loadMap(result.mapFilePath);

            progress.report({ message: "Opening ghost file...", increment: 20 });
            // Open ghost output file
            const ghostDoc = await vscode.workspace.openTextDocument(result.ghostFilePath);
            await vscode.window.showTextDocument(ghostDoc, { preview: false });

            const symbolCount = Object.keys(currentMapData?.symbols ?? {}).length;
            const ghostFileName = path.basename(result.ghostFilePath);

            // Build notification message with risk exposure level
            let hideMessage = `"${ghostFileName}" hidden — ${symbolCount} symbols replaced at Level ${picked.level}`;
            if (result.riskReport) {
              const exposureIcon = { LOW: "🟢", MEDIUM: "🟡", HIGH: "🔴" }[result.riskReport.exposure_level];
              hideMessage += ` | Exposure: ${exposureIcon} ${result.riskReport.exposure_level}`;
            }

            const buttons = ["Copy Ghost File", "Show Map"];
            if (result.riskReport) {
              buttons.push("Risk Report");
            }

            const action = await vscode.window.showInformationMessage(
              hideMessage,
              ...buttons
            );

            if (action === "Copy Ghost File") {
              const content = (await vscode.workspace.openTextDocument(result.ghostFilePath)).getText();
              await vscode.env.clipboard.writeText(content);
              vscode.window.showInformationMessage("Ghost file copied to clipboard.");
            } else if (action === "Show Map") {
              vscode.commands.executeCommand("ghostcodeMap.focus");
            } else if (action === "Risk Report" && result.riskReport) {
              const rr = result.riskReport;
              log("═══ GhostCode Risk Report ═══");
              log(`Privacy Level: ${rr.privacy_level}`);
              log(`Symbols scrubbed: ${rr.total_symbols} (${rr.symbols_by_kind.variables} vars, ${rr.symbols_by_kind.functions} funcs, ${rr.symbols_by_kind.types} types)`);
              log(`Literals: ${rr.literals.scrubbed} scrubbed, ${rr.literals.flagged} flagged, ${rr.literals.kept} kept`);
              log(`Comments ${rr.comments.mode}: ${rr.comments.count}`);
              if (rr.patterns_detected.length > 0) {
                log(`Structural patterns: ${rr.patterns_detected.join(", ")}`);
              }
              log(`Domain exposure: ${rr.exposure_level}`);
              for (const reason of rr.exposure_reasons) {
                log(`  → ${reason}`);
              }
              log("═════════════════════════════");
              showChannel();
            }
          }
        );
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : String(err);
        const userMsg = ghostRunner.formatCliError(raw);
        logError(raw);
        const action = await vscode.window.showErrorMessage(
          `GhostCode hide failed: ${userMsg}`,
          "Show Logs"
        );
        if (action === "Show Logs") {
          showChannel();
        }
      }
    })
  );

  // Hide Project — multi-file hide
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.hideProject", async () => {
      // Step 1: Open multi-file picker
      const fileUris = await vscode.window.showOpenDialog({
        canSelectMany: true,
        canSelectFolders: false,
        filters: {
          "Source files": ["py", "cpp", "cc", "cxx", "c", "h", "hpp", "hxx"],
        },
        title: "Select files to hide",
        defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
      });
      if (!fileUris || fileUris.length === 0) {
        return;
      }

      // Step 2: Confirmation QuickPick
      const confirmItems = fileUris.map((uri) => ({
        label: path.basename(uri.fsPath),
        description: vscode.workspace.asRelativePath(uri),
        picked: true,
        uri,
      }));
      const confirmed = await vscode.window.showQuickPick(confirmItems, {
        canPickMany: true,
        placeHolder: `${fileUris.length} files selected — deselect any to exclude`,
      });
      if (!confirmed || confirmed.length === 0) {
        return;
      }
      const filePaths = confirmed.map((c) => c.uri.fsPath);

      // Step 3: Privacy level picker (Levels 1-2 only)
      const picked = await vscode.window.showQuickPick(
        PRIVACY_LEVELS.filter((p) => p.level <= 2).map((p) => ({
          label: p.label,
          description: p.description,
          level: p.level,
        })),
        { placeHolder: "Select privacy level" }
      );
      if (!picked) {
        return;
      }

      const fileCount = filePaths.length;

      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "GhostCode",
            cancellable: false,
          },
          async (progress) => {
            progress.report({ message: `Analyzing ${fileCount} files...`, increment: 0 });

            progress.report({ message: `Hiding at Level ${picked.level}...`, increment: 20 });
            const result = await ghostRunner.hideMultiple(filePaths, picked.level);

            // Track all ghost files
            const ghostSet = new Set(result.ghostFilePaths);
            mapToGhosts.set(result.mapFilePath, ghostSet);

            for (let i = 0; i < result.ghostFilePaths.length; i++) {
              const ghostFile = result.ghostFilePaths[i];
              ghostToMap.set(ghostFile, result.mapFilePath);
              ghostToSent.set(ghostFile, ghostFile);
              // Snapshot original content
              if (i < filePaths.length) {
                try {
                  const originalContent = fs.readFileSync(filePaths[i], "utf-8");
                  ghostToOriginalContent.set(ghostFile, {
                    content: originalContent,
                    fileName: path.basename(filePaths[i]),
                  });
                } catch {
                  // Non-critical
                }
              }
            }

            progress.report({ message: "Loading ghost map...", increment: 30 });
            loadMap(result.mapFilePath);

            progress.report({ message: "Opening ghost files...", increment: 30 });
            for (const ghostFile of result.ghostFilePaths) {
              const doc = await vscode.workspace.openTextDocument(ghostFile);
              await vscode.window.showTextDocument(doc, { preview: false, preserveFocus: true });
            }

            const symbolCount = Object.keys(currentMapData?.symbols ?? {}).length;

            const action = await vscode.window.showInformationMessage(
              `${fileCount} files hidden — ${symbolCount} symbols replaced at Level ${picked.level}`,
              "Show Map"
            );

            if (action === "Show Map") {
              vscode.commands.executeCommand("ghostcodeMap.focus");
            }
          }
        );
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : String(err);
        const userMsg = ghostRunner.formatCliError(raw);
        logError(raw);
        const action = await vscode.window.showErrorMessage(
          `GhostCode hide failed: ${userMsg}`,
          "Show Logs"
        );
        if (action === "Show Logs") {
          showChannel();
        }
      }
    })
  );

  // Hide Selection — hide only the selected code block
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.hideSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showWarningMessage("GhostCode: No active editor.");
        return;
      }

      const selection = editor.selection;
      if (selection.isEmpty) {
        vscode.window.showWarningMessage("GhostCode: Select some code first, then run Hide Selection.");
        return;
      }

      const filePath = editor.document.uri.fsPath;
      const selectedText = editor.document.getText(selection);

      // Pick privacy level (Levels 1-2 only for selection)
      const picked = await vscode.window.showQuickPick(
        PRIVACY_LEVELS.filter((p) => p.level <= 2).map((p) => ({
          label: p.label,
          description: p.description,
          level: p.level,
        })),
        { placeHolder: "Select privacy level for selection" }
      );
      if (!picked) {
        return;
      }

      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "GhostCode",
            cancellable: false,
          },
          async (progress) => {
            progress.report({ message: "Hiding selection...", increment: 0 });

            // Write selection to a temp file, hide that, then clean up
            const ext = path.extname(filePath) || ".py";
            const tmpDir = os.tmpdir();
            const baseName = path.basename(filePath, ext);
            const tmpFile = path.join(tmpDir, `ghostcode_selection_${baseName}${ext}`);
            fs.writeFileSync(tmpFile, selectedText, "utf-8");

            progress.report({ message: `Hiding at Level ${picked.level}...`, increment: 30 });
            const result = await ghostRunner.hide(tmpFile, picked.level);

            // Track associations
            ghostToMap.set(result.ghostFilePath, result.mapFilePath);
            ghostToSent.set(result.ghostFilePath, result.ghostFilePath);
            ghostToOriginalContent.set(result.ghostFilePath, {
              content: selectedText,
              fileName: `selection from ${path.basename(filePath)}`,
            });

            progress.report({ message: "Loading ghost map...", increment: 30 });
            loadMap(result.mapFilePath);

            progress.report({ message: "Opening ghost file...", increment: 20 });
            const ghostDoc = await vscode.workspace.openTextDocument(result.ghostFilePath);
            await vscode.window.showTextDocument(ghostDoc, {
              preview: false,
              viewColumn: vscode.ViewColumn.Beside,
            });

            const symbolCount = Object.keys(currentMapData?.symbols ?? {}).length;
            const lineCount = selectedText.split("\n").length;

            const action = await vscode.window.showInformationMessage(
              `Selection hidden (${lineCount} lines) — ${symbolCount} symbols replaced at Level ${picked.level}`,
              "Copy Ghost Code"
            );

            if (action === "Copy Ghost Code") {
              const content = (await vscode.workspace.openTextDocument(result.ghostFilePath)).getText();
              await vscode.env.clipboard.writeText(content);
              vscode.window.showInformationMessage("Ghost code copied to clipboard.");
            }

            // Clean up temp file
            try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
          }
        );
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : String(err);
        const userMsg = ghostRunner.formatCliError(raw);
        logError(raw);
        const action = await vscode.window.showErrorMessage(
          `GhostCode hide failed: ${userMsg}`,
          "Show Logs"
        );
        if (action === "Show Logs") {
          showChannel();
        }
      }
    })
  );

  // Reveal File — one click: uses active editor + auto-finds map
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.revealFile", async () => {
      // Use the active editor as the ghost file
      const activeFile = vscode.window.activeTextEditor?.document.uri.fsPath;
      let ghostFilePath: string | undefined;
      let mapFilePath: string | undefined;

      if (activeFile && ghostToMap.has(activeFile)) {
        // Fast path: we know the map for this ghost file
        ghostFilePath = activeFile;
        mapFilePath = ghostToMap.get(activeFile);
      } else if (activeFile) {
        // Active file exists but we don't have a stored map — ask for map only
        ghostFilePath = activeFile;
        const mapUri = await vscode.window.showOpenDialog({
          canSelectMany: false,
          filters: { "Ghost maps": ["json"] },
          title: "Select ghost map file",
          defaultUri: vscode.Uri.file(
            path.join(
              vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "",
              ".ghostcode",
              "maps"
            )
          ),
        });
        if (!mapUri || mapUri.length === 0) {
          return;
        }
        mapFilePath = mapUri[0].fsPath;
      } else {
        vscode.window.showWarningMessage("GhostCode: Open a ghost file first, then run Reveal.");
        return;
      }

      // Check if this map has multiple ghost files
      const siblingGhosts = mapFilePath ? mapToGhosts.get(mapFilePath) : undefined;
      let revealAll = false;

      if (siblingGhosts && siblingGhosts.size > 1) {
        const choice = await vscode.window.showQuickPick(
          [
            { label: "Reveal This File", description: path.basename(ghostFilePath!), all: false },
            { label: `Reveal All (${siblingGhosts.size} files)`, description: "Restore all ghost files from this map", all: true },
          ],
          { placeHolder: "This map covers multiple files" }
        );
        if (!choice) {
          return;
        }
        revealAll = choice.all;
      }

      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "GhostCode",
            cancellable: false,
          },
          async (progress) => {
            if (revealAll && siblingGhosts) {
              // Reveal all files from this map
              const allGhosts = Array.from(siblingGhosts);
              const sentFiles = new Map<string, string>();
              for (const gf of allGhosts) {
                const sent = ghostToSent.get(gf);
                if (sent) {
                  sentFiles.set(gf, sent);
                }
              }

              progress.report({ message: `Restoring ${allGhosts.length} files...`, increment: 30 });
              const results = await ghostRunner.revealMultiple(allGhosts, mapFilePath!, sentFiles);

              progress.report({ message: "Opening restored files...", increment: 40 });
              for (const result of results) {
                const doc = await vscode.workspace.openTextDocument(result.revealedFilePath);
                await vscode.window.showTextDocument(doc, { preview: false, preserveFocus: true });
              }

              // Clean up all associations
              for (const gf of allGhosts) {
                ghostToMap.delete(gf);
                ghostToSent.delete(gf);
                ghostToOriginalContent.delete(gf);
              }
              mapToGhosts.delete(mapFilePath!);

              vscode.window.showInformationMessage(
                `All ${results.length} files restored.`
              );
            } else {
              // Single file reveal
              progress.report({ message: "Reading ghost map...", increment: 0 });

              progress.report({ message: "Restoring symbols...", increment: 30 });
              const sentFile = ghostToSent.get(ghostFilePath!);
              const result = await ghostRunner.reveal(ghostFilePath!, mapFilePath!, sentFile);

              progress.report({ message: "Opening restored file...", increment: 40 });
              const doc = await vscode.workspace.openTextDocument(result.revealedFilePath);
              await vscode.window.showTextDocument(doc, { preview: false });

              // Grab original snapshot before cleanup
              const originalSnapshot = ghostToOriginalContent.get(ghostFilePath!);

              // Clean up the associations
              ghostToMap.delete(ghostFilePath!);
              ghostToSent.delete(ghostFilePath!);
              ghostToOriginalContent.delete(ghostFilePath!);

              // Remove from mapToGhosts set
              if (mapFilePath && mapToGhosts.has(mapFilePath)) {
                const set = mapToGhosts.get(mapFilePath)!;
                set.delete(ghostFilePath!);
                if (set.size === 0) {
                  mapToGhosts.delete(mapFilePath);
                }
              }

              const restoredName = path.basename(result.revealedFilePath);
              const action = await vscode.window.showInformationMessage(
                `Original restored: "${restoredName}"`,
                "Show Diff"
              );

              if (action === "Show Diff" && originalSnapshot) {
                const ext = path.extname(originalSnapshot.fileName);
                const tmpFile = path.join(os.tmpdir(), `ghostcode-original-${Date.now()}${ext}`);
                fs.writeFileSync(tmpFile, originalSnapshot.content, "utf-8");

                const originalUri = vscode.Uri.file(tmpFile);
                const restoredUri = vscode.Uri.file(result.revealedFilePath);
                vscode.commands.executeCommand(
                  "vscode.diff",
                  originalUri,
                  restoredUri,
                  `Original ↔ Revealed: ${restoredName}`
                );
              }
            }
          }
        );
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : String(err);
        const userMsg = ghostRunner.formatCliError(raw);
        logError(raw);
        const action = await vscode.window.showErrorMessage(
          `GhostCode reveal failed: ${userMsg}`,
          "Show Logs"
        );
        if (action === "Show Logs") {
          showChannel();
        }
      }
    })
  );

  // Show Map
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.showMap", async () => {
      const mapUri = await vscode.window.showOpenDialog({
        canSelectMany: false,
        filters: { "Ghost maps": ["json"] },
        title: "Select ghost map file",
        defaultUri: vscode.Uri.file(
          path.join(
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "",
            ".ghostcode",
            "maps"
          )
        ),
      });
      if (!mapUri || mapUri.length === 0) {
        return;
      }

      try {
        loadMap(mapUri[0].fsPath);
        vscode.window.showInformationMessage(
          `GhostCode: Map loaded with ${Object.keys(currentMapData?.symbols ?? {}).length} symbols.`
        );
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : String(err);
        const userMsg = ghostRunner.formatCliError(raw);
        logError(raw);
        const action = await vscode.window.showErrorMessage(
          `GhostCode: Failed to load map: ${userMsg}`,
          "Show Logs"
        );
        if (action === "Show Logs") {
          showChannel();
        }
      }
    })
  );

  // Refresh Map
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.refreshMap", () => {
      treeProvider.refresh();
    })
  );

  // Open Walkthrough
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.openWalkthrough", () => {
      vscode.commands.executeCommand(
        "workbench.action.openWalkthrough",
        "ghostcode.ghostcode#ghostcode.welcome",
        false
      );
    })
  );

  // Show Audit Log
  context.subscriptions.push(
    vscode.commands.registerCommand("ghostcode.showAuditLog", () => {
      showAuditLog(context);
    })
  );

  // --- First-run auto-open walkthrough ---
  const walkthroughSeen = context.globalState.get<boolean>("ghostcode.walkthroughSeen", false);
  if (!walkthroughSeen) {
    context.globalState.update("ghostcode.walkthroughSeen", true);
    // Delay slightly so the extension host is fully ready
    setTimeout(() => {
      vscode.commands.executeCommand(
        "workbench.action.openWalkthrough",
        "ghostcode.ghostcode#ghostcode.welcome",
        false
      );
    }, 1500);
  }

  // --- Editor Decoration Listeners ---
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) {
        applyDecorations(editor, currentMapData);
      }
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((event) => {
      const editor = vscode.window.activeTextEditor;
      if (editor && event.document === editor.document) {
        applyDecorations(editor, currentMapData);
      }
    })
  );

  // Apply decorations to the current editor on activation
  if (vscode.window.activeTextEditor) {
    applyDecorations(vscode.window.activeTextEditor, currentMapData);
  }
}

/** Load a map file and update all views */
function loadMap(mapFilePath: string): void {
  currentMapData = ghostRunner.readMap(mapFilePath);
  vscode.commands.executeCommand("setContext", "ghostcode.mapLoaded", true);
  treeProvider.setMapData(currentMapData);
  updateStatusBar(currentMapData);
  log(`Map loaded: ${mapFilePath} (${Object.keys(currentMapData.symbols).length} symbols)`);

  // Refresh decorations on the active editor
  const editor = vscode.window.activeTextEditor;
  if (editor) {
    applyDecorations(editor, currentMapData);
  }
}

export function deactivate() {
  disposeDecorations();
  disposeStatusBar();
  disposeOutputChannel();
  currentMapData = undefined;
  ghostToMap.clear();
  ghostToOriginalContent.clear();
  mapToGhosts.clear();
}
