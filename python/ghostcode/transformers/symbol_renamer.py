"""Source-level symbol renamer.

Applies ghost token replacements to source code using exact byte offsets
from the AST parser. Replaces from end to start to preserve earlier offsets.

This is NOT regex-based renaming. Every replacement is anchored to a precise
AST-verified location, ensuring:
    - Standard library symbols are never touched
    - Identifiers inside strings are never corrupted
    - Overlapping names (e.g., 'count' vs 'counter') are handled correctly
"""

from ..mapping.ghost_map import GhostMap
from ..parsers.base import ParseResult, Symbol


class SymbolRenamer:
    """Renames user-defined symbols in source code using AST-verified offsets."""

    def __init__(self, ghost_map: GhostMap):
        self._map = ghost_map

    def rename(self, parse_result: ParseResult) -> str:
        """Apply ghost token replacements to source code.

        Args:
            parse_result: Output from parser containing symbols and source.

        Returns:
            Transformed source code with all user symbols replaced.
        """
        source = parse_result.source_code
        replacements = []

        for symbol in parse_result.symbols:
            token = self._map.add_symbol(
                original=symbol.name,
                kind=symbol.kind,
                scope=symbol.scope,
                source_file=parse_result.file_path,
            )

            for loc in symbol.locations:
                # Verify the original name is actually at this offset
                actual = source[loc.offset:loc.end_offset]
                if actual == symbol.name:
                    replacements.append((loc.offset, loc.end_offset, token))

        # Deduplicate: same offset might be registered by both declaration
        # and reference walks
        seen_offsets: set[int] = set()
        unique_replacements = []
        for start, end, token in replacements:
            if start not in seen_offsets:
                seen_offsets.add(start)
                unique_replacements.append((start, end, token))

        # Sort by offset DESCENDING — replace from end to preserve offsets
        unique_replacements.sort(key=lambda r: r[0], reverse=True)

        for start, end, token in unique_replacements:
            source = source[:start] + token + source[end:]

        return source
