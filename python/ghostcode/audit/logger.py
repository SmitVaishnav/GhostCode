"""Audit logger.

Every ghost hide/reveal invocation produces an immutable JSON log entry.
The security team can review exactly what was scrubbed, what was kept,
and what warnings were raised.

Log location: ~/.ghostcode/audit/YYYY-MM-DD.jsonl
Format: JSON Lines (one JSON object per line, append-only)

Each entry contains:
    - Timestamp and user info
    - Action (hide/reveal)
    - File details and scrub level
    - Symbol/literal/comment counts
    - SHA-256 hashes of input and output
    - Any warnings raised
"""

import getpass
import hashlib
import json
import os
import platform
from datetime import datetime, timezone


def _get_audit_dir() -> str:
    """Get the audit log directory."""
    return os.path.join(os.path.expanduser("~"), ".ghostcode", "audit")


def _hash_content(content: str) -> str:
    """SHA-256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def _hash_file(filepath: str) -> str:
    """SHA-256 hash of a file's contents."""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (FileNotFoundError, PermissionError):
        return "unavailable"


class AuditLogger:
    """Append-only audit logger for GhostCode operations."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._audit_dir = _get_audit_dir()

    def log_hide(self, source_files: list[str], scrub_level: int,
                 function_isolated: str | None,
                 symbols_scrubbed: int, literals_scrubbed: int,
                 literals_flagged: int, literals_kept: int,
                 comments_stripped: int, warnings: list[dict],
                 ghost_output_path: str, map_path: str,
                 ghost_output_content: str = ""):
        """Log a hide operation."""
        if not self._enabled:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "hide",
            "user": getpass.getuser(),
            "hostname": platform.node(),
            "source_files": source_files,
            "scrub_level": scrub_level,
            "function_isolated": function_isolated,
            "symbols_scrubbed": symbols_scrubbed,
            "literals_scrubbed": literals_scrubbed,
            "literals_flagged": literals_flagged,
            "literals_kept": literals_kept,
            "comments_stripped": comments_stripped,
            "warnings": [w.get("type", str(w)) for w in warnings],
            "warning_count": len(warnings),
            "ghost_output_hash": (
                _hash_content(ghost_output_content) if ghost_output_content
                else _hash_file(ghost_output_path)
            ),
            "map_hash": _hash_file(map_path),
        }

        self._write(entry)

    def log_reveal(self, input_file: str, map_file: str,
                   mode: str, symbols_restored: int,
                   new_symbols: list[str],
                   new_dependencies: list[str],
                   annotations_count: int,
                   confidence: str, confidence_score: int,
                   output_path: str):
        """Log a reveal operation."""
        if not self._enabled:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "reveal",
            "user": getpass.getuser(),
            "hostname": platform.node(),
            "input_file": input_file,
            "map_used": map_file,
            "mode": mode,
            "symbols_restored": symbols_restored,
            "new_symbols_detected": len(new_symbols),
            "new_symbols": new_symbols,
            "new_dependencies": new_dependencies,
            "annotations": annotations_count,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "output_hash": _hash_file(output_path),
        }

        self._write(entry)

    def _write(self, entry: dict):
        """Append a log entry to today's log file."""
        os.makedirs(self._audit_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(self._audit_dir, f"{today}.jsonl")

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_recent_entries(self, count: int = 10) -> list[dict]:
        """Read the most recent audit log entries."""
        entries = []
        if not os.path.exists(self._audit_dir):
            return entries

        log_files = sorted(
            [f for f in os.listdir(self._audit_dir) if f.endswith(".jsonl")],
            reverse=True,
        )

        for log_file in log_files:
            path = os.path.join(self._audit_dir, log_file)
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            if len(entries) >= count:
                break

        return entries[-count:]
