# GhostCode

**Privacy proxy for developers — hide your proprietary symbols before sharing code with AI.**

The code is visible. The meaning is invisible.

## The Problem

Every time you paste code into ChatGPT, Claude, or Copilot, you're exposing:
- Variable names that reveal business logic (`customer_revenue`, `fraud_score`, `trading_algorithm`)
- Function names that expose architecture (`calculate_quarterly_earnings`, `sync_patient_records`)
- String literals with API endpoints, internal URLs, and domain-specific constants
- Comments explaining proprietary algorithms

**Your company's IP is leaking, one prompt at a time.**

## The Solution

GhostCode replaces every user-defined symbol with an opaque token before you share code with AI:

```
# Before (your code)                    # After (what the AI sees)
def calculate_revenue(transactions):     def gf_001(gv_001):
    total_income = 0                         gv_002 = 0
    for txn in transactions:                 for gv_003 in gv_001:
        if txn.is_verified:                      if gv_003.gv_004:
            total_income += txn.amount               gv_002 += gv_003.gv_005
    return total_income                      return gv_002
```

The AI gives you a working answer using ghost tokens. GhostCode then restores all original names — your code is fully functional, and the AI never saw your business logic.

## Features

### Core
- **Hide File** — Replace all symbols with ghost tokens (gv_001, gf_001, gt_001)
- **Reveal File** — Restore original names from the ghost map
- **Hide Selection** — Right-click to hide just selected code
- **Hide Project** — Multi-file hide with a shared ghost map across files
- **4 Privacy Levels** — From names-only (L1) to full isolation with dimension generalization (L4)
- **Python & C++ Support** — AST-based parsing for accurate symbol detection

### Intelligence
- **Literal Scrubbing** (Level 2+) — Classifies string/number literals as SCRUB, KEEP, or FLAG
- **Function Isolation** (Level 3+) — Extracts a single function with dependency stubs
- **Risk Report** — Pre-send exposure assessment (LOW / MEDIUM / HIGH)
- **AI Change Detection** — Annotates what the AI modified after reveal

### Developer Experience
- **Ghost Map Sidebar** — Tree view of all symbol mappings grouped by kind
- **Token Highlighting** — Color-coded decorations with hover tooltips
- **CodeLens Actions** — Clickable "Hide/Reveal" links above functions
- **Side-by-Side Diff** — Compare original vs restored code after reveal
- **Copy to Clipboard** — One-click copy ghost code for pasting into AI
- **Keyboard Shortcuts** — `Cmd+Shift+G H` (hide), `Cmd+Shift+G S` (selection), `Cmd+Shift+G P` (project)

### Security & Compliance
- **Audit Log Dashboard** — Visual webview showing all hide/reveal operations with SHA-256 hashes
- **Repo-Level Config** — `.ghostcode.yaml` for security team policies (min scrub level, banned patterns, enforce audit)
- **Encrypted Maps** — Optional passphrase-protected ghost maps (AES-128-CBC)
- **Immutable Audit Trail** — JSON Lines logs at `~/.ghostcode/audit/`

## Quick Start

1. **Install** from the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=SmitVaishanav.ghostcode)
2. **Open** a Python or C++ file
3. **Run** `Cmd+Shift+G H` or Command Palette > "Ghost: Hide File"
4. **Pick** a privacy level (1-4)
5. **Copy** the ghost file and paste into your AI tool
6. **Paste** the AI's response back into the ghost file
7. **Run** "Ghost: Reveal File" — original names restored

## Privacy Levels

| Level | What's Hidden | Use Case |
|-------|--------------|----------|
| **1** | Symbol names + comments | Quick questions, code review |
| **2** | + String/number literals | Sharing with external AI |
| **3** | + Function isolation with stubs | Sensitive algorithm help |
| **4** | + Dimension generalization | Maximum privacy |

## How It Works

```
Your Code --> [Parse AST] --> [Replace Symbols] --> Ghost Code --> AI
                                      |
                                Ghost Map (JSON)
                                      |
AI Response --> [Restore Tokens] --> [Annotate Changes] --> Your Code (restored)
```

1. **Parse** — AST analysis identifies user-defined symbols (functions, classes, variables, parameters)
2. **Replace** — Each symbol gets a deterministic token (gv for variables, gf for functions, gt for types)
3. **Map** — Bidirectional ghost map stores all mappings with O(1) lookup
4. **Share** — Ghost code goes to the AI, map stays local
5. **Restore** — After AI responds, tokens are swapped back to original names
6. **Annotate** — Changes the AI made are detected and marked

## Ghost Map

The ghost map is a JSON file that stores every symbol mapping:

```json
{
  "version": "1.0",
  "created": "2026-03-01T04:30:00Z",
  "files": ["order_processor.py"],
  "symbols": {
    "gf_001": { "original": "process_customer_order", "kind": "function", "scope": "" },
    "gv_001": { "original": "customer_name", "kind": "parameter", "scope": "process_customer_order" },
    "gv_002": { "original": "cart_items", "kind": "parameter", "scope": "process_customer_order" },
    "gv_003": { "original": "subtotal", "kind": "variable", "scope": "process_customer_order" }
  }
}
```

## Audit Log

Every hide and reveal operation is logged to `~/.ghostcode/audit/` as immutable JSON Lines files. The built-in Audit Log Dashboard (Command Palette > "Ghost: Audit Log") provides:

- Summary stats (total hides, reveals, symbols processed)
- Filterable table with timestamps, actions, file details
- SHA-256 hashes of inputs and outputs for compliance verification
- Color-coded confidence scores for reveal operations

## Repo Configuration

Security teams can enforce policies via `.ghostcode.yaml` in the project root:

```yaml
min_scrub_level: 2
block_level_1: true
enforce_audit: true
encrypt_maps: true
banned_patterns:
  - "*.key"
  - "*.pem"
  - "*credentials*"
allowed_llm_endpoints:
  - "http://internal-llm.company.com:8080"
```

## Keyboard Shortcuts

| Shortcut | Command |
|----------|---------|
| `Cmd+Shift+G H` | Hide current file |
| `Cmd+Shift+G S` | Hide selection |
| `Cmd+Shift+G P` | Hide project (multi-file) |

## Requirements

- VS Code 1.85+
- Python 3.8+ (bundled with extension, auto-detected)

## Architecture

```
ghostcode-vscode/
  src/
    extension.ts      # Commands, state management, UI flows
    ghostRunner.ts    # Python CLI interface
    types.ts          # TypeScript interfaces
    mapViewer.ts      # Ghost Map tree view
    decorations.ts    # Token highlighting & hover
    statusBar.ts      # Status bar indicator
    auditViewer.ts    # Audit log webview dashboard
    outputChannel.ts  # Logging
  python/
    ghostcode/        # Bundled Python CLI
      cli.py          # CLI entry point
      parsers/        # Python & C++ AST parsers
      transformers/   # Symbol renamer, literal scrubber, isolator
      mapping/        # Ghost map, token generator, encryption
      reveal/         # Code revealer, diff analyzer
      audit/          # Audit logger
      config.py       # Configuration system
```

## How is this different from just renaming variables?

GhostCode is not find-and-replace. It:
- **Parses the AST** to distinguish user symbols from builtins, imports, and framework code
- **Preserves semantics** — the ghost code is valid, runnable code
- **Handles scope** — same name in different scopes gets different tokens
- **Scrubs literals** — domain-revealing strings and numbers are classified and replaced
- **Detects AI changes** — after reveal, you see exactly what the AI added or modified
- **Provides compliance** — audit logs, SHA-256 hashes, repo-level policy enforcement

## License

MIT

---

**GhostCode** — Your code. Your names. Your business.
