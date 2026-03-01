import * as vscode from "vscode";
import * as path from "path";
import { GhostMapData, GhostSymbolEntry, KIND_LABELS } from "./types";

/** A tree item representing either a category group or a symbol entry */
class GhostMapItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly children?: GhostMapItem[]
  ) {
    super(label, collapsibleState);
  }
}

/**
 * TreeDataProvider for the Ghost Map sidebar view.
 * Groups symbols by kind category (Variables, Functions, Types, etc.)
 */
export class GhostMapTreeProvider implements vscode.TreeDataProvider<GhostMapItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<GhostMapItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private mapData: GhostMapData | undefined;

  /** Update the map data and refresh the tree */
  setMapData(data: GhostMapData | undefined): void {
    this.mapData = data;
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: GhostMapItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: GhostMapItem): GhostMapItem[] {
    if (!this.mapData) {
      return [];
    }

    // Root level: return category groups
    if (!element) {
      return this.buildCategoryGroups();
    }

    // Category level: return children
    return element.children ?? [];
  }

  private buildCategoryGroups(): GhostMapItem[] {
    if (!this.mapData) {
      return [];
    }

    // Group symbols by display category
    const groups: Map<string, { token: string; entry: GhostSymbolEntry }[]> = new Map();

    for (const [token, entry] of Object.entries(this.mapData.symbols)) {
      const category = KIND_LABELS[entry.kind] ?? "Other";
      if (!groups.has(category)) {
        groups.set(category, []);
      }
      groups.get(category)!.push({ token, entry });
    }

    // Sort categories and build tree items
    const categoryOrder = [
      "Variables", "Functions", "Types", "Constants", "Strings", "Macros", "Namespaces", "Other",
    ];

    const items: GhostMapItem[] = [];

    // Prepend "Files" group when map covers multiple files
    if (this.mapData.files.length > 1) {
      const fileChildren = this.mapData.files.map((filePath) => {
        const item = new GhostMapItem(
          path.basename(filePath),
          vscode.TreeItemCollapsibleState.None
        );
        item.tooltip = filePath;
        item.iconPath = new vscode.ThemeIcon("file-code");
        return item;
      });

      const filesGroup = new GhostMapItem(
        `Files (${this.mapData.files.length})`,
        vscode.TreeItemCollapsibleState.Expanded,
        fileChildren
      );
      filesGroup.iconPath = new vscode.ThemeIcon("folder-opened");
      items.push(filesGroup);
    }

    for (const category of categoryOrder) {
      const entries = groups.get(category);
      if (!entries || entries.length === 0) {
        continue;
      }

      const children = entries.map(({ token, entry }) => {
        const item = new GhostMapItem(
          `${token} → ${entry.original}`,
          vscode.TreeItemCollapsibleState.None
        );
        item.tooltip = `Kind: ${entry.kind}\nScope: ${entry.scope || "(global)"}\nFiles: ${entry.files.join(", ")}`;
        item.iconPath = new vscode.ThemeIcon("symbol-variable");
        return item;
      });

      const groupItem = new GhostMapItem(
        `${category} (${entries.length})`,
        vscode.TreeItemCollapsibleState.Expanded,
        children
      );
      groupItem.iconPath = new vscode.ThemeIcon("symbol-folder");
      items.push(groupItem);
    }

    return items;
  }

  /** Refresh the tree view */
  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }
}
