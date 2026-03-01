# What is GhostCode?

GhostCode is a **privacy proxy** for developers who use AI coding assistants.

## The Problem

When you paste code into ChatGPT, Copilot, or Claude, you expose private symbol names — variable names that reveal business logic, function names tied to proprietary algorithms, and string literals containing internal URLs or keys.

## The Solution

GhostCode replaces every meaningful symbol with an opaque token:

```python
# Before (your real code)
def calculate_revenue(quarterly_sales, tax_rate):
    return quarterly_sales * (1 - tax_rate)

# After (what the AI sees)
def gf_001(gv_001, gv_002):
    return gv_001 * (1 - gv_002)
```

The AI can still reason about the code structure, suggest fixes, and refactor — it just never sees your private names.

When you get your answer back, GhostCode **restores every symbol** automatically.
