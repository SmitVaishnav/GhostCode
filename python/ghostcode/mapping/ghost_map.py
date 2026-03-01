"""Bidirectional ghost map.

Stores the mapping between ghost tokens and original symbols.
Position-independent — maps by identity, not line number.
Supports multi-file projects with consistent token assignment.
"""

import json
import os
from datetime import datetime, timezone

from .token_generator import TokenGenerator


class SymbolEntry:
    """A single symbol's mapping entry."""

    def __init__(self, ghost_token: str, original: str, kind: str,
                 scope: str = "", files: list[str] | None = None):
        self.ghost_token = ghost_token
        self.original = original
        self.kind = kind
        self.scope = scope
        self.files = files or []

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "kind": self.kind,
            "scope": self.scope,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, ghost_token: str, data: dict) -> "SymbolEntry":
        return cls(
            ghost_token=ghost_token,
            original=data["original"],
            kind=data["kind"],
            scope=data.get("scope", ""),
            files=data.get("files", []),
        )


class GhostMap:
    """Bidirectional mapping between ghost tokens and original symbols.

    Provides O(1) lookup in both directions:
        ghost_token → original name
        original name → ghost_token
    """

    def __init__(self):
        self.token_gen = TokenGenerator()
        self._entries: dict[str, SymbolEntry] = {}
        self._reverse: dict[str, str] = {}
        self._metadata: dict = {
            "version": "1.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "files": [],
        }
        self.warnings: list[dict] = []

    def add_symbol(self, original: str, kind: str, scope: str = "",
                   source_file: str = "") -> str:
        """Register a symbol and return its ghost token.

        If the symbol was already registered, returns the existing token.

        Args:
            original: Original symbol name.
            kind: Symbol kind (variable, function, class, etc.).
            scope: Qualified scope for disambiguation.
            source_file: File where the symbol was found.

        Returns:
            Ghost token string.
        """
        token = self.token_gen.get_token(original, kind, scope)

        if token in self._entries:
            entry = self._entries[token]
            if source_file and source_file not in entry.files:
                entry.files.append(source_file)
        else:
            self._entries[token] = SymbolEntry(
                ghost_token=token,
                original=original,
                kind=kind,
                scope=scope,
                files=[source_file] if source_file else [],
            )
            self._reverse[original] = token

        if source_file and source_file not in self._metadata["files"]:
            self._metadata["files"].append(source_file)

        return token

    def add_warning(self, warning_type: str, symbol: str,
                    line: int, file: str, detail: str = ""):
        """Record a warning (e.g., unresolved template symbol)."""
        self.warnings.append({
            "type": warning_type,
            "symbol": symbol,
            "line": line,
            "file": file,
            "detail": detail,
        })

    def get_original(self, ghost_token: str) -> str | None:
        """Look up the original name for a ghost token."""
        entry = self._entries.get(ghost_token)
        return entry.original if entry else None

    def get_ghost_token(self, original: str) -> str | None:
        """Look up the ghost token for an original name."""
        return self._reverse.get(original)

    def get_entry(self, ghost_token: str) -> SymbolEntry | None:
        """Get full entry details for a ghost token."""
        return self._entries.get(ghost_token)

    def all_tokens(self) -> set[str]:
        """Return set of all ghost tokens."""
        return set(self._entries.keys())

    def forward_map(self) -> dict[str, str]:
        """Return ghost_token → original mapping."""
        return {token: entry.original for token, entry in self._entries.items()}

    def reverse_map(self) -> dict[str, str]:
        """Return original → ghost_token mapping."""
        return dict(self._reverse)

    @property
    def symbol_count(self) -> int:
        return len(self._entries)

    def _to_dict(self) -> dict:
        """Serialize map to dictionary."""
        return {
            **self._metadata,
            "symbols": {
                token: entry.to_dict()
                for token, entry in self._entries.items()
            },
            "warnings": self.warnings,
        }

    def save(self, filepath: str, passphrase: str | None = None):
        """Save map to file.

        Args:
            filepath: Output path. Use .ghost extension for encrypted,
                      .json for plaintext.
            passphrase: If provided, encrypt with this passphrase.
                        If filepath ends in .ghost, passphrase is required.
        """
        from .encryption import is_encrypted, save_encrypted

        data = self._to_dict()

        if passphrase or is_encrypted(filepath):
            if not passphrase:
                from .encryption import prompt_passphrase
                passphrase = prompt_passphrase(confirm=True)
            save_encrypted(data, filepath, passphrase)
        else:
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    @classmethod
    def load(cls, filepath: str, passphrase: str | None = None) -> "GhostMap":
        """Load map from file (encrypted or plaintext).

        Args:
            filepath: Path to map file (.ghost or .json).
            passphrase: Decryption passphrase for .ghost files.
        """
        from .encryption import is_encrypted, load_encrypted

        if is_encrypted(filepath):
            if not passphrase:
                from .encryption import prompt_passphrase
                passphrase = prompt_passphrase(confirm=False)
            data = load_encrypted(filepath, passphrase)
        else:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

        gmap = cls()
        gmap._metadata = {
            "version": data.get("version", "1.0"),
            "created": data.get("created", ""),
            "files": data.get("files", []),
            "original_comments": data.get("original_comments", {}),
            "original_file": data.get("original_file", ""),
            "ghost_file": data.get("ghost_file", ""),
        }
        gmap.warnings = data.get("warnings", [])

        for token, entry_data in data.get("symbols", {}).items():
            entry = SymbolEntry.from_dict(token, entry_data)
            gmap._entries[token] = entry
            gmap._reverse[entry.original] = token

        return gmap

    def summary(self) -> str:
        """Return a human-readable summary of the map."""
        kinds: dict[str, int] = {}
        for entry in self._entries.values():
            kinds[entry.kind] = kinds.get(entry.kind, 0) + 1

        lines = [f"GhostMap: {self.symbol_count} symbols across {len(self._metadata['files'])} file(s)"]
        for kind, count in sorted(kinds.items()):
            lines.append(f"  {kind}: {count}")
        if self.warnings:
            lines.append(f"  warnings: {len(self.warnings)}")
        return "\n".join(lines)
