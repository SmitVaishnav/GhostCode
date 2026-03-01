# Check Python Setup

GhostCode uses a Python CLI under the hood. You need:

1. **Python 3.9+** installed
2. The **ghostcode** package:
   ```bash
   pip install ghostcode
   ```

## Configure Python Path

If your Python isn't on the default PATH, set it in VS Code settings:

**Settings** > search `ghostcode.pythonPath` > enter the full path to your Python interpreter.

Common paths:
- **macOS/Linux venv**: `./venv/bin/python3`
- **Conda**: `~/miniconda3/envs/myenv/bin/python`
- **System**: `/usr/bin/python3`

## Verify It Works

Open the Command Palette and run **Ghost: Hide File**. If you see an error about the module not being found, double-check your Python path and package installation.
