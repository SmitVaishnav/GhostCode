# Reveal to Restore

When the AI gives you a response, paste it back into the ghost file (or use the AI's modified version), then run **Reveal** to restore all original symbols.

## Steps

1. Open the ghost file in the editor
2. Run **Ghost: Reveal File** from the Command Palette
3. If the map was loaded in the same session, reveal is automatic — no file picker needed
4. Otherwise, you'll be prompted to select the map JSON file

## What Happens

- Every ghost token (`gv_001`, `gf_002`, etc.) is replaced with its original name
- The restored file opens in the editor
- You can use **Show Diff** to compare the ghost file with the restored version

## Tips

- Keep the ghost map file safe — without it, tokens can't be reversed
- Maps are saved in `.ghostcode/maps/` by default
- You can re-hide the same file at a different privacy level anytime
