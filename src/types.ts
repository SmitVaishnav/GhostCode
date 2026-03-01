import * as vscode from "vscode";

/** Mirrors SymbolEntry.to_dict() from ghostcode/mapping/ghost_map.py */
export interface GhostSymbolEntry {
  original: string;
  kind: string;
  scope: string;
  files: string[];
}

/** Mirrors GhostMap._to_dict() from ghostcode/mapping/ghost_map.py */
export interface GhostMapData {
  version: string;
  created: string;
  files: string[];
  symbols: Record<string, GhostSymbolEntry>;
  warnings: GhostWarning[];
}

export interface GhostWarning {
  type: string;
  symbol: string;
  line: number;
  file: string;
  detail: string;
}

/** Pre-send risk report from the hide CLI command */
export interface RiskReport {
  privacy_level: number;
  file_count: number;
  total_symbols: number;
  symbols_by_kind: {
    variables: number;
    functions: number;
    types: number;
    constants: number;
    strings: number;
    macros: number;
  };
  literals: {
    scrubbed: number;
    flagged: number;
    kept: number;
  };
  comments: {
    count: number;
    mode: string;
  };
  function_isolated: boolean;
  isolated_function: string;
  patterns_detected: string[];
  exposure_level: "LOW" | "MEDIUM" | "HIGH";
  exposure_reasons: string[];
  warnings_count: number;
}

/** Result from the hide CLI command */
export interface HideResult {
  ghostFilePath: string;
  mapFilePath: string;
  riskReport?: RiskReport;
}

/** Result from multi-file hide CLI command */
export interface HideMultiResult {
  ghostFilePaths: string[];
  mapFilePath: string;
}

/** Result from the reveal CLI command */
export interface RevealResult {
  revealedFilePath: string;
}

/** Token prefix → decoration color mapping */
export const TOKEN_PREFIXES: Record<string, { color: string; label: string }> = {
  gv: { color: "rgba(66, 135, 245, 0.15)", label: "Variable" },
  gf: { color: "rgba(245, 200, 66, 0.15)", label: "Function" },
  gt: { color: "rgba(66, 245, 200, 0.15)", label: "Type" },
  gc: { color: "rgba(245, 130, 66, 0.15)", label: "Constant" },
  gs: { color: "rgba(180, 66, 245, 0.15)", label: "String" },
  gm: { color: "rgba(245, 66, 66, 0.15)", label: "Macro" },
  gn: { color: "rgba(66, 245, 100, 0.15)", label: "Namespace" },
};

/** Ghost token regex: matches gv_001, gf_012, gt_999, etc. */
export const GHOST_TOKEN_REGEX = /\bg[vftcsmn]_\d{3}\b/g;

/** Kind labels for tree view grouping */
export const KIND_LABELS: Record<string, string> = {
  variable: "Variables",
  parameter: "Variables",
  field: "Variables",
  function: "Functions",
  method: "Functions",
  class: "Types",
  struct: "Types",
  enum: "Types",
  typedef: "Types",
  type_alias: "Types",
  enum_constant: "Variables",
  constant: "Constants",
  string: "Strings",
  macro: "Macros",
  namespace: "Namespaces",
};

/** Privacy level descriptions for QuickPick */
export const PRIVACY_LEVELS: { level: number; label: string; description: string }[] = [
  { level: 1, label: "Level 1", description: "Rename symbols + strip comments" },
  { level: 2, label: "Level 2", description: "+ Scrub string/numeric literals" },
  { level: 3, label: "Level 3", description: "+ Function isolation with stubs" },
  { level: 4, label: "Level 4", description: "+ Dimension generalization" },
];
