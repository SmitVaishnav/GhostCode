"""Code revealer — restores ghost tokens to original names.

Handles both pure code files and AI responses containing mixed content
(prose + code blocks). When processing AI responses, separates zones
and applies different restoration strategies to each.

Zone types:
    CODE_BLOCK  — fenced code blocks (```lang ... ```)
    INLINE_CODE — backtick spans in prose (`gv_001`)
    PROSE       — natural language text
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from ..mapping.ghost_map import GhostMap


class ZoneType(Enum):
    PROSE = "prose"
    CODE_BLOCK = "code_block"
    INLINE_CODE = "inline_code"


@dataclass
class Zone:
    """A segment of an AI response with a specific type."""
    type: ZoneType
    content: str
    start: int
    end: int
    language: str = ""  # for code blocks


@dataclass
class RevealResult:
    """Result of revealing an AI response."""
    restored_code: str
    restored_explanation: str
    symbols_restored: int
    new_symbols: list[str] = field(default_factory=list)
    new_dependencies: list[str] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)


# Ghost token pattern — matches any ghost token format
GHOST_TOKEN_PATTERN = re.compile(r"\bg[vftcsnmx]_\d{3}\b")

# Pattern for token with common suffixes in prose
GHOST_TOKEN_PROSE_PATTERN = re.compile(
    r"\bg[vftcsnmx]_\d{3}(?='s|[-/]|(?:\b))"
)


class CodeRevealer:
    """Restores ghost tokens to original names in code and AI responses."""

    def __init__(self, ghost_map: GhostMap):
        self._map = ghost_map
        self._forward = ghost_map.forward_map()
        # Sort by token length descending to avoid substring collisions
        self._sorted_tokens = sorted(
            self._forward.keys(), key=len, reverse=True
        )

    def reveal_code(self, ghost_source: str,
                    original_ghost: str | None = None,
                    diff_result=None) -> tuple[str, int, list[str]]:
        """Reveal a pure code file (no prose).

        Args:
            ghost_source: The AI-modified ghost code to reveal.
            original_ghost: The original ghost file sent to AI (optional).
                If provided, changed blocks are annotated with descriptive
                comments like '# --- AI MODIFIED: desc ---'.
            diff_result: Optional DiffResult from DiffAnalyzer (unused, reserved).

        Returns:
            Tuple of (restored_source, count_restored, new_symbols).
        """
        restored = ghost_source
        count = 0

        for token in self._sorted_tokens:
            original = self._forward[token]
            if token in restored:
                restored = restored.replace(token, original)
                count += 1

        # Restore anonymized comments from map metadata
        # Tokens appear wrapped in comment syntax: # [gc_001], """[gc_001]""", // [gc_001]
        # We try each wrapper pattern, then fall back to bare token
        original_comments = self._map._metadata.get("original_comments", {})
        for comment_token, original_text in original_comments.items():
            replaced = False
            # Try wrapped patterns first (most specific to least)
            for pattern in [
                f'"""{comment_token}"""',
                f"'''{comment_token}'''",
                f"/* {comment_token} */",
                f"// {comment_token}",
                f"# {comment_token}",
            ]:
                if pattern in restored:
                    restored = restored.replace(pattern, original_text)
                    count += 1
                    replaced = True
                    break
            # Fall back to bare token
            if not replaced and comment_token in restored:
                restored = restored.replace(comment_token, original_text)
                count += 1

        new_symbols = self._detect_new_symbols(restored)
        for sym in new_symbols:
            restored = restored.replace(sym, f"NEW_{sym}")

        # Annotate new/changed lines if original ghost file is provided
        if original_ghost is not None:
            restored = self._annotate_new_lines(restored, original_ghost)

        return restored, count, new_symbols

    def _reveal_original(self, original_ghost: str) -> str:
        """Reveal the original ghost file for fair comparison."""
        original_revealed = original_ghost
        for token in self._sorted_tokens:
            original_name = self._forward[token]
            if token in original_revealed:
                original_revealed = original_revealed.replace(token, original_name)

        # Restore comments in original too (try wrapped patterns first)
        original_comments = self._map._metadata.get("original_comments", {})
        for comment_token, original_text in original_comments.items():
            for pattern in [
                f'"""{comment_token}"""',
                f"'''{comment_token}'''",
                f"/* {comment_token} */",
                f"// {comment_token}",
                f"# {comment_token}",
                comment_token,
            ]:
                if pattern in original_revealed:
                    original_revealed = original_revealed.replace(pattern, original_text)
                    break

        return original_revealed

    def _detect_comment_style(self, code: str) -> str:
        """Auto-detect comment prefix from surrounding code."""
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                return "//"
            if stripped.startswith("#") and not stripped.startswith("#include"):
                return "#"
        # Fallback based on common patterns
        if "def " in code or "import " in code:
            return "#"
        if "#include" in code or "int main" in code or "::" in code:
            return "//"
        return "#"

    def _annotate_new_lines(self, revealed: str, original_ghost: str) -> str:
        """Annotate changed blocks with descriptive AI-change comments.

        Compares the revealed code against the original ghost file
        (after revealing it too) and inserts block-level annotations like:
            # --- AI MODIFIED: changed '+' to '-' ---
            # --- AI ADDED: null-safety check ---
        """
        from .diff_analyzer import DiffAnalyzer

        original_revealed = self._reveal_original(original_ghost)

        analyzer = DiffAnalyzer()
        blocks = analyzer.detect_change_blocks(original_revealed, revealed)

        if not blocks:
            return revealed

        comment_prefix = self._detect_comment_style(revealed)
        lines = revealed.splitlines()

        # Insert annotations backwards to preserve line numbers
        for block in reversed(blocks):
            description = analyzer.describe_change(block)

            if block.block_type == "added":
                label = "AI ADDED"
            elif block.block_type == "deleted":
                label = "AI REMOVED"
            else:
                label = "AI MODIFIED"

            annotation = f"{comment_prefix} --- {label}: {description} ---"

            # Insert annotation above the block's start line
            insert_at = block.start_line
            if insert_at <= len(lines):
                # Match indentation of the first line of the block
                if insert_at < len(lines) and lines[insert_at].strip():
                    indent = len(lines[insert_at]) - len(lines[insert_at].lstrip())
                    annotation = " " * indent + annotation
                lines.insert(insert_at, annotation)

        return "\n".join(lines)

    def reveal_ai_response(self, response: str) -> RevealResult:
        """Reveal a full AI response (prose + code blocks).

        Parses the response into zones, applies zone-specific restoration,
        and produces both restored code and translated explanation.
        """
        zones = self._parse_zones(response)
        restored_parts = []
        code_blocks = []
        symbols_restored = 0

        for zone in zones:
            if zone.type == ZoneType.CODE_BLOCK:
                revealed, count, new_syms = self.reveal_code(zone.content)
                code_blocks.append(revealed)
                symbols_restored += count
                # Reconstruct fenced block
                lang = zone.language
                restored_parts.append(f"```{lang}\n{revealed}\n```")

            elif zone.type == ZoneType.INLINE_CODE:
                revealed = self._reveal_inline(zone.content)
                if revealed != zone.content:
                    symbols_restored += 1
                restored_parts.append(f"`{revealed}`")

            else:
                # Prose — apply token replacement with word boundaries
                revealed = self._reveal_prose(zone.content)
                restored_parts.append(revealed)

        restored_full = "".join(restored_parts)

        # Extract just the code blocks for the code output
        restored_code = "\n\n".join(code_blocks) if code_blocks else ""

        # Detect new symbols across all code blocks
        all_new = []
        for block in code_blocks:
            all_new.extend(self._detect_new_symbols(block))
        all_new = list(set(all_new))

        # Detect new dependencies
        new_deps = self._detect_new_dependencies(code_blocks)

        result = RevealResult(
            restored_code=restored_code,
            restored_explanation=restored_full,
            symbols_restored=symbols_restored,
            new_symbols=all_new,
            new_dependencies=new_deps,
        )

        return result

    def _parse_zones(self, text: str) -> list[Zone]:
        """Parse AI response into typed zones."""
        zones = []
        pos = 0

        # Pattern for fenced code blocks
        code_block_pattern = re.compile(
            r"```(\w*)\n(.*?)```", re.DOTALL
        )

        for match in code_block_pattern.finditer(text):
            # Add prose before this code block
            if match.start() > pos:
                prose = text[pos:match.start()]
                # Split prose further into inline code and text
                zones.extend(self._parse_inline_zones(prose, pos))

            # Add the code block
            zones.append(Zone(
                type=ZoneType.CODE_BLOCK,
                content=match.group(2),
                start=match.start(),
                end=match.end(),
                language=match.group(1),
            ))
            pos = match.end()

        # Add remaining prose after last code block
        if pos < len(text):
            zones.extend(self._parse_inline_zones(text[pos:], pos))

        return zones

    def _parse_inline_zones(self, text: str, base_offset: int) -> list[Zone]:
        """Split prose text into PROSE and INLINE_CODE zones."""
        zones = []
        pos = 0

        for match in re.finditer(r"`([^`]+)`", text):
            # Prose before inline code
            if match.start() > pos:
                zones.append(Zone(
                    type=ZoneType.PROSE,
                    content=text[pos:match.start()],
                    start=base_offset + pos,
                    end=base_offset + match.start(),
                ))

            # Inline code
            zones.append(Zone(
                type=ZoneType.INLINE_CODE,
                content=match.group(1),
                start=base_offset + match.start(),
                end=base_offset + match.end(),
            ))
            pos = match.end()

        # Remaining prose
        if pos < len(text):
            zones.append(Zone(
                type=ZoneType.PROSE,
                content=text[pos:],
                start=base_offset + pos,
                end=base_offset + len(text),
            ))

        return zones

    def _reveal_inline(self, code_span: str) -> str:
        """Reveal tokens in an inline code span."""
        result = code_span
        for token in self._sorted_tokens:
            if token in result:
                result = result.replace(token, self._forward[token])
        return result

    def _reveal_prose(self, text: str) -> str:
        """Reveal tokens in prose with word-boundary matching.

        Handles common prose patterns:
            gv_001-related  → connectionPool-related
            gv_001's value  → connectionPool's value
            gf_001/gf_002   → update_matrix/validate_input
        """
        result = text
        for token in self._sorted_tokens:
            original = self._forward[token]
            # Word boundary match that allows common suffixes
            pattern = re.compile(
                r"\b" + re.escape(token) + r"(?='s|[-/.,;:!?\s\)]|$)"
            )
            result = pattern.sub(original, result)
        return result

    def _detect_new_symbols(self, code: str) -> list[str]:
        """Find ghost-pattern tokens not in our map."""
        found = set(GHOST_TOKEN_PATTERN.findall(code))
        known = self._map.all_tokens()
        # Also exclude tokens we already replaced (they shouldn't be here)
        return sorted(found - known)

    def _detect_new_dependencies(self, code_blocks: list[str]) -> list[str]:
        """Detect new #include or import statements the AI introduced."""
        deps = []
        for block in code_blocks:
            for line in block.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#include") or stripped.startswith("import ") or stripped.startswith("from "):
                    deps.append(stripped)
        return deps
