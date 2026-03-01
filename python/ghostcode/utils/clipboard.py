"""Cross-platform clipboard integration.

Copies ghost output to clipboard so the developer can paste directly
into their LLM chat. Uses pbcopy (macOS), xclip (Linux), or clip (Windows).
"""

import subprocess
import sys


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard.

    Returns True on success, False if clipboard is unavailable.
    """
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif sys.platform.startswith("linux"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif sys.platform == "win32":
        cmd = ["clip"]
    else:
        return False

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        proc.communicate(text.encode("utf-8"))
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def clipboard_available() -> bool:
    """Check if clipboard commands are available."""
    if sys.platform == "darwin":
        cmd = ["which", "pbcopy"]
    elif sys.platform.startswith("linux"):
        cmd = ["which", "xclip"]
    elif sys.platform == "win32":
        cmd = ["where", "clip"]
    else:
        return False

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=2
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
