"""Multi-file consistency handler.

Ensures that the same user symbol gets the same ghost token across
all files in a project. If `BatterySimulator` appears in main.cpp,
utils.cpp, and tests.cpp, it gets `gt_001` everywhere.

Strategy:
    1. Parse all files first (collect all symbols across all files).
    2. Build a unified symbol table.
    3. Generate tokens from the unified table.
    4. Apply renaming to each file using the shared map.
"""

import os

from ..mapping.ghost_map import GhostMap
from ..parsers.base import BaseParser, ParseResult
from ..transformers.comment_stripper import CommentStripper
from ..transformers.symbol_renamer import SymbolRenamer


def process_multiple_files(
    file_paths: list[str],
    parser: BaseParser,
    ghost_map: GhostMap,
    strip_comments: bool = True,
) -> list[tuple[str, str, int, int]]:
    """Process multiple files with consistent ghost token assignment.

    All files share the same GhostMap, so identical symbols across files
    get identical ghost tokens.

    Args:
        file_paths: List of source files to process.
        parser: Language-appropriate parser instance.
        ghost_map: Shared ghost map (tokens assigned here).
        strip_comments: Whether to strip comments.

    Returns:
        List of (file_path, ghost_source, symbol_count, comment_count) tuples.
    """
    results = []
    stripper = CommentStripper() if strip_comments else None

    # Pass 1: Parse all files to discover all symbols
    parse_results: list[ParseResult] = []
    for fpath in file_paths:
        pr = parser.parse(fpath)
        parse_results.append(pr)

    # Pass 2: Pre-register all symbols into the shared map
    # This ensures consistent token assignment regardless of file order
    all_symbols = []
    for pr in parse_results:
        for sym in pr.symbols:
            all_symbols.append((sym.name, sym.kind, sym.scope, pr.file_path))

    # Sort for deterministic assignment
    all_symbols.sort(key=lambda s: (s[1], s[2], s[0]))
    for name, kind, scope, fpath in all_symbols:
        ghost_map.add_symbol(
            original=name, kind=kind, scope=scope,
            source_file=fpath,
        )

    # Pass 3: Apply transformations to each file
    for pr in parse_results:
        source = pr.source_code
        comment_count = 0

        # Strip comments first
        if stripper and pr.comments:
            source, comment_count = stripper.strip(source, pr.comments)
            # Re-parse for accurate offsets on clean source
            import tempfile
            ext = os.path.splitext(pr.file_path)[1]
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False
            ) as tmp:
                tmp.write(source)
                tmp_path = tmp.name

            try:
                clean_pr = parser.parse(tmp_path)
                clean_pr.file_path = pr.file_path
                clean_pr.source_code = source
            finally:
                os.unlink(tmp_path)
        else:
            clean_pr = pr

        # Rename using the shared map
        renamer = SymbolRenamer(ghost_map)
        ghost_source = renamer.rename(clean_pr)

        sym_count = len(clean_pr.symbols)
        results.append((pr.file_path, ghost_source, sym_count, comment_count))

    return results
