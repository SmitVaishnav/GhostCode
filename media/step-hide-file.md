# Hide Your First File

## Steps

1. Open a Python (`.py`) or C/C++ file in the editor
2. Run **Ghost: Hide File** from the Command Palette (`Cmd+Shift+P`) or use the shortcut `Cmd+Shift+G H`
3. Pick a **privacy level**:

| Level | What it does |
|-------|-------------|
| **1** | Renames symbols + strips comments |
| **2** | + Scrubs string and numeric literals |
| **3** | + Isolates a single function with stubs |
| **4** | + Generalizes array dimensions |

4. For Level 3+, you can optionally specify a function name to isolate

## What Happens

- A **ghost file** opens with all symbols replaced by tokens like `gv_001`, `gf_002`
- A **ghost map** (JSON) is saved that records every replacement
- The Ghost Map sidebar populates with all symbol mappings
- Tokens are color-coded in the editor by kind (variables, functions, types, etc.)

Copy the ghost file content and paste it into your AI assistant.
